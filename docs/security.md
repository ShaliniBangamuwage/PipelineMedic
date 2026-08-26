# Security

The service redacts bearer tokens, GitHub-style tokens, password/token/secret assignments, and API keys before storing or sending log content. Webhook signatures use HMAC SHA-256. Uploads are limited to `.log` and `.txt` and capped by `MAX_LOG_SIZE_BYTES`. CORS is restricted to `FRONTEND_URL`.

Authentication uses bcrypt password hashes, short-lived JWT access tokens, and hashed rotating refresh tokens in HTTP-only cookies. With `AUTH_ENABLED=true`, resource queries require authenticated organization membership and mutation dependencies enforce role thresholds. `JWT_SECRET` must be a long random value in enabled deployments.

This portfolio MVP has no authentication, authorization, rate limiting, encrypted log retention, or production secret manager. Do not expose it publicly with sensitive logs. Production should add identity, tenant isolation, audit events, short retention, GitHub App credentials, provider timeouts, and structured generic error responses. AI prompts must treat logs as untrusted data and only transmit redacted content.
