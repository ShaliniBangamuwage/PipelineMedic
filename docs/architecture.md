# Architecture

PipelineMedic is a React/Vite client backed by a FastAPI service. The API processes untrusted CI logs, redacts likely secrets, classifies failures using weighted rules, and stores reports through SQLAlchemy. SQLite is the default local store; PostgreSQL is supported through `DATABASE_URL` and Compose.

```mermaid
flowchart LR
  UI[React dashboard] --> API[FastAPI REST API]
  API --> LP[Log processor]
  LP --> RB[Rule based analyzer]
  RB --> DB[(SQLAlchemy database)]
  GH[GitHub workflow_run webhook] --> API
  API -. optional .-> AI[Groq analyzer]
```

Demo flow: form or file -> validation -> ANSI/timestamp cleanup and redaction -> evidence extraction -> weighted classification -> database -> result/history APIs.

Webhook flow: raw body -> HMAC verification -> event filtering -> failed run deduplication -> queued processing -> optional GitHub archive retrieval -> redacted analysis persistence.

AI fallback: rule-based analysis is always available. Groq responses are schema-validated and evidence is restricted to extracted log lines before persistence.
