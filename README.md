# PipelineMedic

PipelineMedic is an AI-assisted CI/CD failure triage dashboard for extracting error evidence, classifying failed workflows, and tracking resolution. The current MVP works without external AI credentials through a deterministic rule-based analyzer.

## Features

- Paste or upload `.log`/`.txt` workflow output
- ANSI/timestamp cleanup, duplicate collapse, blank-line reduction, and likely-secret redaction
- Weighted classification for compilation, tests, dependencies, configuration, database, containers, deployment, authorization, and network failures
- Optional Groq analysis with strict JSON validation and automatic rule-based fallback
- GitHub workflow log archive retrieval with bounded, safe ZIP extraction
- Persisted reports, repository management, feedback, resolution, similarity search, and signed webhook intake
- Persisted reports, history, resolution state, dashboard metrics, and signed webhook intake
- Responsive DevOps-style React dashboard with demo-mode labeling

## Status

Phase 1 authentication and tenancy are implemented on the `advanced-features` branch. Set `AUTH_ENABLED=true` to require JWT authentication and organization headers; leave it false for the portfolio demo workflow.

## Stack

React + Vite + TypeScript, FastAPI, Pydantic Settings, SQLAlchemy, SQLite/PostgreSQL, Docker Compose, Pytest, and GitHub Actions.

## Prerequisites

Node.js 22+ and npm. Python 3.12+ for local backend execution, or Docker Desktop for the Compose workflow.

## Local setup

```powershell
Copy-Item apps/backend/.env.example apps/backend/.env
Copy-Item apps/frontend/.env.example apps/frontend/.env
Push-Location apps/backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH='.'
uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```powershell
Push-Location apps/frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The API health endpoint is `http://localhost:8000/api/health`.

With `REDIS_URL` configured, run the long-lived consumer from `apps/backend` with:

```powershell
$env:PYTHONPATH='.'; py -3.12 -m app.worker
```

Leave `REDIS_URL` empty to retain inline local/demo processing.

## Docker

```powershell
docker compose up --build
```

The dashboard is served at `http://localhost` and the API at `http://localhost:8000`.

## Tests and builds

```powershell
Push-Location apps/backend
$env:PYTHONPATH='.'
python -m pytest -q
Push-Location ..\frontend
npm run lint
npm run type-check
npm test
npm run build
```

## Authentication and organizations

When authentication is enabled, register at `/register`, log in at `/login`, and select an organization at `/organizations`. Access tokens stay in memory and refresh tokens are stored in an HTTP-only cookie. Repository, analysis, dashboard, feedback, and similarity queries are scoped by `X-Organization-ID`. Roles are OWNER, ADMIN, DEVELOPER, and VIEWER; mutations require the corresponding minimum role. Never use the development JWT default in a deployed environment.

## Environment

Backend settings are documented in [apps/backend/.env.example](apps/backend/.env.example), including database URL, CORS origin, webhook secret, optional GitHub/Groq credentials, and log limits. Frontend settings are in [apps/frontend/.env.example](apps/frontend/.env.example). Never commit `.env` files or secrets.

## Documentation

- [Architecture](docs/architecture.md)
- [API reference](docs/api-reference.md)
- [Database schema](docs/database-schema.md)
- [GitHub webhook setup](docs/github-webhook-setup.md)
- [Security](docs/security.md)

## Sample analysis

Use the Analyze log page and select a sample button, or paste a fixture from `samples/logs`. Reports are stored locally in `apps/backend/pipelinemedic.db` when using the default SQLite configuration.

## Roadmap

1. Add broader organization/member frontend administration and production observability.
2. Add GitHub workflow-run persistence and background queue execution.
3. Replace keyword similarity with pgvector embeddings.
4. Add browser tests and production deployment manifests.

## License

MIT. See [LICENSE](LICENSE).

## Author

PipelineMedic portfolio project by Shalini Bangamuwage.
