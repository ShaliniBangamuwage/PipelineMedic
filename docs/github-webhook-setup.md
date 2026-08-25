# GitHub Webhook Setup

Set the payload URL to `https://your-host/api/webhooks/github`, content type to `application/json`, and configure a random secret as `GITHUB_WEBHOOK_SECRET`. Select the `Workflow runs` event. Localhost cannot receive GitHub callbacks without a tunnel such as an approved development tunnel.

The endpoint verifies `X-Hub-Signature-256`, accepts `ping`, ignores non-workflow events, and only queues completed failures. Sample payloads live in `samples/webhook-payloads`. A configured GitHub token and log-download worker are planned for the next phase.
