# API Reference

- `GET /api/health` returns service status.
- `POST /api/demo/analyze` accepts multipart `log`, optional `.log`/`.txt` `file`, `repository`, `workflow`, `branch`, and `commit_sha` fields.
- `GET /api/analyses` returns `{items, page, pageSize, total}`.
- `GET /api/analyses/{id}` returns a stored report.
- `PATCH /api/analyses/{id}/resolve` marks a report resolved.
- `GET /api/dashboard/summary` returns stored aggregate metrics.
- `POST /api/webhooks/github` accepts signed `ping` and `workflow_run` payloads.

Errors use FastAPI's current `{detail: string}` response for this MVP. Production should standardize this into `{error:{code,message,details}}` alongside authentication and rate limiting.
