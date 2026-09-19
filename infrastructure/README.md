# Infrastructure

| File | Purpose |
|---|---|
| `Dockerfile.backend` | Production image for web, worker and beat. Non-root, health-checked. |
| `docker-compose.yml` | Full local/staging stack: Postgres, Redis, web, worker, beat. |
| `render.yaml` | Render blueprint. Secrets are `sync: false` and set in the dashboard. |

The frontend deploys to Vercel from `frontend/` and needs no container - see
[../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).

Two things to keep in mind whichever host you use:

* **Run exactly one beat process.** Two means every periodic task fires twice, including
  order expiry and automatic refunds.
* **Never put a secret in a file in this directory.** Everything sensitive is an
  environment variable set by the platform.
