# Database Schema

The MVP has `repositories` and `analyses` tables. A repository has many analyses; an analysis stores source, category, severity, confidence, evidence excerpt, cleaned log, resolution state, and workflow metadata. IDs are UUID strings and timestamps are timezone-aware.

```mermaid
erDiagram
  REPOSITORIES ||--o{ ANALYSES : contains
  REPOSITORIES { string id PK string owner string name string default_branch boolean active }
  ANALYSES { string id PK string repository_id FK string category string severity float confidence text cleaned_log boolean resolved }
```

PostgreSQL is the intended deployment database. pgvector and separate workflow/action/feedback tables remain planned extensions.
