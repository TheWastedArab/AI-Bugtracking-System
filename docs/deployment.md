# Deployment

## Local

Run `scripts/start.ps1`, `python -m backend.worker`, and (with AI dependencies) `python -m backend.worker --train` in separate terminals. The API binds to loopback; the extension requires HTTPS for non-local hosts and scopes SecretStorage tokens to the configured origin.

Local model weights are under `artifacts/`. Fresh clones train/download them explicitly. Missing weights do not prevent reporting.

## Containers and PostgreSQL

Install Docker with Compose. Copy `.env.example` to `.env` and replace both secrets. Use an alphanumeric DB password or URL-encode it in the connection URL. Then run `docker compose up --build -d`.

Migrations run before API/worker startup. PostgreSQL and ClamAV use persistent volumes. Uploads fail until ClamAV has usable signatures. PostgreSQL has no exposed host port. Docker deployment was not executed locally because Docker was unavailable.

The base API image supports severity and lexical retrieval. For semantic inference, build the API from `Dockerfile.ai`, override its command to `python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`, and set `SEMANTIC_MODEL_PATH=/app/artifacts/all-MiniLM-L6-v2`. The weights must be mounted under `/app/artifacts`. `docker compose --profile ai up -d trainer` starts the training worker.

Set `DOMAIN` and use `docker compose --profile https up -d` for Caddy HTTPS. Validate DNS, certificates, proxy trust, backups, and monitoring before exposing the service. Caddy limits request bodies to 11 MB.

## Notifications

`MAIL_TRANSPORT=preview` is the default. Preview files contain verification codes and must remain private. For SMTP, set `MAIL_TRANSPORT=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, and credentials if required. `SMTP_SECURITY` must be `starttls` or `ssl`; plaintext is rejected and certificates are validated. Set these on the worker process or through an explicit Compose override.

Outbox failures retry up to five attempts and retain only the exception type. Monitor pending/failed rows. Delivery is at-least-once: a crash after SMTP acceptance but before DB commit may send a duplicate. Delivered bodies are removed from the database. Pending verification mail necessarily contains its delivery code; verification records themselves contain only hashes.

The `push` profile starts self-hosted ntfy with default-deny access. Configure its user/token/topic and HTTPS endpoint, then set `NTFY_URL` (full topic URL) and `NTFY_TOKEN` on the worker. The public ntfy.sh endpoint is rejected. The default Compose file deliberately does not expose or provision ntfy credentials.

## Attachments

Use `CLAMAV_HOST`/`CLAMAV_PORT` for an internal clamd service, or `CLAMSCAN_PATH` for a local executable with current signatures. Content/extension checks, image dimensions, UTF-8 logs, and the 10 MB limit are enforced before storage. Downloads require project access and use attachment disposition plus `nosniff`.

Without scanning, uploads fail closed. `ALLOW_UNSCANNED_ATTACHMENTS=true` permits explicitly labelled local-demo uploads; it must not be enabled in production.

## Models and acceptance

Run one training worker per deployment. New artifacts are written before the DB pointer changes; failure retains an earlier model. API and trainer must share the same durable artifact path. The offline Eclipse model uses benchmark identities and is not a live project model. Successful training is currently the activation gate; research accuracy targets are evaluated separately.

Before production, test PostgreSQL restore, real scanner rejection, email/push, TLS renewal, concurrent writes, worker recovery, 50,000-bug performance, accessibility, usability, and security. No availability or regulatory-compliance claim has been established.
