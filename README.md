# PipelineMedic

PipelineMedic is a multi-tenant CI/CD failure analysis platform that receives GitHub Actions failure events, processes workflow logs asynchronously, identifies likely root causes, and presents actionable failure evidence through an authenticated dashboard.

## 1. Problem

Developers often lose time triaging CI failures because the relevant signal is buried inside noisy workflow logs, rerun metadata, and multiple GitHub Actions steps. PipelineMedic addresses that by receiving workflow failure events, retrieving the log archive, extracting the evidence that matters, and classifying likely root causes before the team even opens the job details.

## 2. Features

Implemented and verified features include:

- GitHub Actions webhook integration for workflow failure events
- Asynchronous job processing with Redis-backed queueing
- GitHub Actions log retrieval and ZIP extraction with safe file selection
- Deterministic CI failure classification with rule-based fallback
- Unit-test failure detection for pytest-style failures
- Failure evidence extraction and cleaned log presentation
- Multi-tenant organization scoping for users, repositories, jobs, and analyses
- Authenticated frontend dashboard with repository and organization management
- Repository credential storage with write-only API behavior for PAT and webhook secret metadata
- Run-attempt-aware persistence so reruns do not overwrite previous analysis records
- PostgreSQL-backed persistence with Dockerized local services

## 3. Architecture

```text
GitHub Actions
      |
      v
GitHub Webhook
      |
      v
FastAPI Backend
      |
      v
Redis Queue
      |
      v
Worker
      |
      +--> GitHub Logs
      |
      v
Analyzer
      |
      v
PostgreSQL
      |
      v
React Frontend
```

## 4. Hybrid AI Analysis

PipelineMedic uses a hybrid failure-analysis model:

- Deterministic rule-based analysis remains the primary path and is always run first.
- AI is an optional evidence-based fallback/enrichment layer for low-confidence or unsupported cases only.
- The AI layer never blindly overrides strong deterministic evidence such as TypeScript compiler diagnostics, pytest failures, or configuration errors with actual supporting log lines.
- If AI is disabled, not configured, or the provider returns malformed data, the deterministic analyzer continues working normally.

Required AI settings in backend `.env`:

```env
AI_ENABLED=false
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
AI_TIMEOUT_SECONDS=15
AI_MAX_LOG_CHARS=30000
```

Behavior:

- `AI_ENABLED=false` disables provider calls entirely.
- Missing or invalid provider config disables AI safely without blocking deterministic analysis.
- Prompts are sanitized before being sent to the provider; tokens, PATs, bearer headers, DB URLs with passwords, webhook secrets, and private keys are redacted.
- The AI can only suggest diagnoses supported by the sanitized evidence package; unsupported hallucinations are rejected.

## 5. Tech Stack

- Frontend: React, Vite, TypeScript, Vitest
- Backend: FastAPI, SQLAlchemy, Pydantic
- Database: PostgreSQL with SQLite fallback for local tests
- Queue: Redis
- CI/log processing: GitHub Actions, Python log parsing and classification
- Containerization: Docker Compose

## 6. Security / Multi-tenancy

Resources are organization-scoped. Users can only access repositories, workflow runs, analyses, jobs, and settings that belong to their current organization. Stored credentials are not exposed through API responses, and PAT/webhook secret values are treated as write-only inputs.

## 7. Local setup

```powershell
docker compose up --build
```

The application is available through the local Docker stack using the existing Compose configuration.

For direct backend development:

```powershell
Copy-Item apps/backend/.env.example apps/backend/.env
Copy-Item apps/frontend/.env.example apps/frontend/.env
cd apps/backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH='.'
uvicorn app.main:app --reload --port 8000
```

For the frontend:

```powershell
cd apps/frontend
npm install
npm run dev
```

Never commit real PATs or webhook secrets. Keep `.env` files local and untracked.

### GitHub authentication

Create a GitHub OAuth App and configure its authorization callback URL as:

```text
http://localhost:8000/api/auth/github/callback
```

Set these backend-only variables in `apps/backend/.env` (never in frontend/Vite configuration):

```text
GITHUB_OAUTH_CLIENT_ID=
GITHUB_OAUTH_CLIENT_SECRET=
GITHUB_OAUTH_CALLBACK_URL=http://localhost:8000/api/auth/github/callback
```

GitHub authentication requests only identity and verified-email access. It does not import repositories or replace the existing PAT-based repository connection.

## 8. Screenshots

Planned placeholders for portfolio use:

- Login screen
- Overview dashboard
- UNIT_TEST_FAILURE detail
- Jobs page
- Repositories page

## 9. Testing

Current verified status after final validation:

- Backend tests: 92 passed
- Frontend tests: 25 passed
- Frontend production build: succeeded

## 10. Documentation

- [docs/architecture.md](docs/architecture.md)
- [docs/api-reference.md](docs/api-reference.md)
- [docs/database-schema.md](docs/database-schema.md)
- [docs/github-webhook-setup.md](docs/github-webhook-setup.md)
- [docs/security.md](docs/security.md)

## 11. License

MIT. See [LICENSE](LICENSE).
