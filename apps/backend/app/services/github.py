from io import BytesIO
from zipfile import ZipFile
from pathlib import PurePosixPath
import hashlib
import re
import httpx

class GitHubClientError(Exception): pass
class GitHubTemporaryError(GitHubClientError): pass
class GitHubPermanentError(GitHubClientError): pass

class GitHubClient:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=15.0, follow_redirects=False)
        self.headers = {"Accept":"application/vnd.github+json", "X-GitHub-Api-Version":"2022-11-28", "Authorization":f"Bearer {token}"}

    def _request(self, method: str, url: str, **kwargs):
        try:
            response = self.client.request(method, url, headers=self.headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise GitHubTemporaryError("GitHub request timed out") from exc
        except httpx.HTTPError as exc:
            raise GitHubTemporaryError("GitHub request unavailable") from exc
        rate_limited = response.status_code == 429 or (response.status_code == 403 and (response.headers.get("retry-after") or response.headers.get("x-ratelimit-remaining") == "0"))
        if rate_limited or response.status_code in (408,) or response.status_code >= 500:
            raise GitHubTemporaryError(f"GitHub request temporarily unavailable ({response.status_code})")
        if response.status_code in (401, 403, 404, 422):
            raise GitHubPermanentError(f"GitHub request rejected ({response.status_code})")
        if response.status_code >= 400:
            raise GitHubPermanentError("GitHub request failed")
        return response

    def pull_requests_for_run(self, owner: str, repo: str, branch: str, sha: str) -> list[dict]:
        candidates = []
        for page in range(1, 6):
            response = self._request("GET", f"https://api.github.com/repos/{owner}/{repo}/pulls", params={"state":"all","head":f"{owner}:{branch}","per_page":100,"page":page})
            batch = response.json(); candidates.extend(batch)
            if len(batch) < 100: break
        return sorted([item for item in candidates if item.get("head", {}).get("sha") == sha], key=lambda item: (not item.get("state") == "open", item.get("number", 0)))

    def comments(self, owner: str, repo: str, number: int) -> list[dict]:
        comments = []
        for page in range(1, 6):
            response = self._request("GET", f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments", params={"per_page":100,"page":page})
            batch = response.json(); comments.extend(batch)
            if len(batch) < 100: break
        return comments

    def create_comment(self, owner: str, repo: str, number: int, body: str) -> dict:
        return self._request("POST", f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments", json={"body": body}).json()

    def update_comment(self, owner: str, repo: str, comment_id: str, body: str) -> dict:
        return self._request("PATCH", f"https://api.github.com/repos/{owner}/{repo}/issues/comments/{comment_id}", json={"body": body}).json()

    def source_context(self, owner: str, repo: str, paths: list[str], ref: str, max_bytes: int = 200_000) -> tuple[str, str]:
        chunks: list[str] = []; used = 0
        secret = re.compile(r"(?i)(token|secret|password|authorization|api[_-]?key)\s*[=:]\s*[^\s,;]+")
        for path in paths[:20]:
            normalized = PurePosixPath(path)
            if normalized.is_absolute() or ".." in normalized.parts or path.startswith((".env", ".git/")) or normalized.name in {"id_rsa", "id_ed25519", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}:
                continue
            response = self._request("GET", f"https://api.github.com/repos/{owner}/{repo}/contents/{path}", params={"ref": ref})
            data = response.json()
            if data.get("encoding") != "base64" or not data.get("content"): continue
            import base64
            text = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            text = secret.sub(r"\1=[REDACTED]", text)
            encoded_size = len(text.encode())
            if used + encoded_size > max_bytes: break
            chunks.append(f"FILE: {path}\n{text}"); used += encoded_size
        context = "\n\n".join(chunks)
        return context, hashlib.sha256(context.encode()).hexdigest()

    def workflow_logs(self, owner: str, repo: str, run_id: int, max_bytes: int = 10_000_000) -> str:
        url=f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
        try:
            response=self.client.get(url, headers=self.headers)
            if response.status_code in (301,302,307,308):
                location=response.headers.get("location")
                if not location: raise GitHubClientError("GitHub log redirect missing location")
                response=self.client.get(location, headers={"Accept":"application/zip"})
            if response.status_code in (401,403,404): raise GitHubClientError(f"GitHub log request rejected ({response.status_code})")
            if response.status_code >= 400: raise GitHubClientError("GitHub log request failed")
            if len(response.content) > max_bytes: raise GitHubClientError("GitHub log archive exceeds the configured size limit")
            with ZipFile(BytesIO(response.content)) as archive:
                chunks=[]
                for entry in archive.infolist():
                    if entry.is_dir() or not entry.filename.lower().endswith((".txt",".log")): continue
                    if PurePosixPath(entry.filename).is_absolute() or ".." in PurePosixPath(entry.filename).parts: continue
                    if entry.file_size > max_bytes: continue
                    chunks.append(archive.read(entry).decode("utf-8", errors="replace"))
            return "\n".join(chunks)
        except (httpx.TimeoutException, httpx.HTTPError, OSError) as exc:
            raise GitHubClientError("GitHub log request unavailable") from exc
