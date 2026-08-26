# GitHub Webhook Setup

Set the payload URL to `https://your-host/api/webhooks/github`, content type to `application/json`, and configure a random secret as `GITHUB_WEBHOOK_SECRET`. Select the `Workflow runs` event. Localhost cannot receive GitHub callbacks without a tunnel such as an approved development tunnel.

The endpoint verifies `X-Hub-Signature-256`, accepts `ping`, ignores non-workflow events, and only queues completed failures. With `GITHUB_TOKEN`, the worker downloads the workflow ZIP and extracts safe text entries; without it, it stores a metadata-only report. Sample payloads live in `samples/webhook-payloads`.
