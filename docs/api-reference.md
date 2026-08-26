# API Reference

- `GET /api/health` returns service status.
- `POST /api/demo/analyze` accepts multipart `log`, optional `.log`/`.txt` `file`, `repository`, `workflow`, `branch`, and `commit_sha` fields.
- `GET /api/analyses` returns `{items, page, pageSize, total}` and accepts `source`, `category`, `severity`, `resolved`, `repository`, and `search` filters.
- `GET /api/analyses/{id}` returns a stored report.
- `PATCH /api/analyses/{id}/resolve` marks a report resolved and accepts optional `actual_solution`.
- `POST /api/analyses/{id}/feedback` accepts `{accurate, actual_category, actual_solution}`.
- `GET /api/analyses/{id}/similar` returns category-matched incidents with deterministic similarity scores.
- `GET/POST /api/repositories`, `GET/PATCH/DELETE /api/repositories/{id}` manage repository registrations. Delete deactivates rather than erases history.
- `GET /api/dashboard/summary` returns stored aggregate metrics.
- `POST /api/webhooks/github` accepts signed `ping` and `workflow_run` payloads.
- `POST/GET/DELETE /api/organizations/{id}/invitations` create, list, and revoke invitations; `POST /api/invitations/{token}/accept` accepts a matching invitation.
- `GET/POST /api/organizations`, `GET/PATCH/DELETE /api/organizations/{id}`, and member endpoints manage organization membership when authentication is enabled.

Errors use FastAPI's current `{detail: string}` response for this MVP. Production should standardize this into `{error:{code,message,details}}` alongside authentication and rate limiting.
