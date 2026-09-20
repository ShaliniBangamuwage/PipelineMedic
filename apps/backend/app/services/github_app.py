from __future__ import annotations

from datetime import datetime, timezone
import logging
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import settings

logger = logging.getLogger("pipelinemedic.github_app")
GITHUB_API = "https://api.github.com"


class GitHubAppError(Exception):
    pass


class GitHubAppTemporaryError(GitHubAppError):
    pass


class GitHubAppPermanentError(GitHubAppError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def configured() -> bool:
    return bool(settings.github_app_id and settings.github_app_private_key and settings.github_app_slug)


def _private_key() -> str:
    return settings.github_app_private_key.replace("\\n", "\n")


def app_jwt() -> str:
    if not configured():
        raise GitHubAppError("GitHub App is not configured")
    now = int(datetime.now(timezone.utc).timestamp())
    try:
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": settings.github_app_id},
            _private_key(),
            algorithm="RS256",
        )
    except (ValueError, TypeError, jwt.PyJWTError) as exc:
        raise GitHubAppError("GitHub App private key is invalid") from exc


def install_url(state: str) -> str:
    base = settings.github_app_install_url.strip() or f"https://github.com/apps/{settings.github_app_slug}/installations/new"
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{urlencode({'state': state})}"


class GitHubAppClient:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=15.0, follow_redirects=False)
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {app_jwt()}",
        }

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            response = self.client.request(method, url, headers=self.headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise GitHubAppTemporaryError("GitHub App request timed out") from exc
        except httpx.HTTPError as exc:
            raise GitHubAppTemporaryError("GitHub App request unavailable") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise GitHubAppTemporaryError("GitHub App request temporarily unavailable")
        if response.status_code >= 400:
            raise GitHubAppPermanentError("GitHub App request rejected", response.status_code)
        return response

    def installation(self, installation_id: str) -> dict:
        return self._request("GET", f"{GITHUB_API}/app/installations/{installation_id}").json()

    def installation_token(self, installation_id: str) -> str:
        response = self._request("POST", f"{GITHUB_API}/app/installations/{installation_id}/access_tokens")
        token = response.json().get("token")
        if not token:
            raise GitHubAppPermanentError("GitHub did not return an installation token")
        return token

    def repositories(self, installation_id: str, page: int = 1, per_page: int = 30) -> dict:
        token = self.installation_token(installation_id)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {token}",
        }
        try:
            response = self.client.get(
                f"{GITHUB_API}/installation/repositories",
                headers=headers,
                params={"page": page, "per_page": min(max(per_page, 1), 100)},
            )
        except httpx.TimeoutException as exc:
            raise GitHubAppTemporaryError("GitHub repository request timed out") from exc
        except httpx.HTTPError as exc:
            raise GitHubAppTemporaryError("GitHub repository request unavailable") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise GitHubAppTemporaryError("GitHub repository request temporarily unavailable")
        if response.status_code >= 400:
            raise GitHubAppPermanentError("GitHub repository request rejected", response.status_code)
        return response.json()


def installation_token(installation_id: str) -> str:
    return GitHubAppClient().installation_token(installation_id)
