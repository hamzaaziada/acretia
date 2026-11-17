# Deploying Acretia

One host, Docker Compose: `caddy` (TLS, security headers) in front of `app` (API + web UI). SQLite in WAL mode on a named volume is the system of record (D-003). Postgres, Redis and MinIO are optional profiles.

## 1. Prerequisites

- Docker Engine 24+ with Compose v2.24+ (`docker compose version`), BuildKit on (default).
- 4 vCPU, 8 GB RAM, 30 GB disk for the full image (document parsing with docling pulls CPU PyTorch). Build with `ACRETIA_WITH_EXTRAS=0` for a core-only image of about 1.5 GB; the engines then fall back to `pdfplumber`/`poppler` and SQLite.
- For a public host: a DNS A/AAAA record for your domain pointing at the server, and ports 80 and 443 open (80 is needed for ACME).
- Outbound HTTPS from the `app` container to the hosts you enable in `DECISIONS.md` only: `llm.meshpool.ai` (models), `www.sec.gov` / `data.sec.gov` (filings), and any data-room connector you turn on.

## 2. Configure

```bash
cp .env.example .env          # .env is git-ignored; compose treats it as optional
```

Edit `.env`. Variables the stack reads (all have defaults):

| Variable | Default | Purpose |
|---|---|---|
| `ACRETIA_DOMAIN` | `localhost` | Public host name. Also becomes `ACRETIA_ALLOWED_HOSTS` (DNS-rebinding guard). |
| `ACRETIA_TLS` | `internal` | `internal` = Caddy's local CA (self-signed, for local/LAN). Set to an e-mail address to get Let's Encrypt certificates for a real domain. |
| `ACRETIA_HTTP_PORT` / `ACRETIA_HTTPS_PORT` | `80` / `443` | Host ports published by Caddy. |
| `ACRETIA_ALLOWED_ORIGINS` | none | Extra trusted origins (comma-separated) if a second host name fronts the app. |
| `ACRETIA_LLM_MODE` | `live` | `replay` serves recorded fixtures with no model calls. |
| `ACRETIA_ALLOW_SIGNUP` | off | Leave off in production; create the first org with `create-org` (below). |
| `ACRETIA_APP_CPUS` / `ACRETIA_APP_MEM` | `4` / `8g` | App container limits. |
| `ACRETIA_WITH_EXTRAS` | `1` | Build arg: install `requirements-extras.txt` (docling, duckdb, formulon). |
| `SEC_USER_AGENT` | none | Required for live SEC requests: `"Company contact@yourdomain"`. |

### Keys (never committed)

- Model keys (`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, ...) go in `.env` on the server, or in your orchestrator's secret store, and reach the container as environment variables. `.env` is in `.gitignore` and `.dockerignore`, so it is never baked into an image.
- The MeshPool key is bound to the host `llm.meshpool.ai` (D-021): put it in `.env` as the variable `.env.example` names and keep the provider base URL on `llm.meshpool.ai`. Do not reuse it for other hosts.
- The session-signing and at-rest encryption key defaults to a random 0600 file `secret.key` inside `/data`, created on first start. To manage it yourself set `ACRETIA_SECRET_KEY` (hex, 32+ bytes). Back it up with the data: losing it makes stored secrets unreadable.
- Postgres and MinIO credentials are file secrets in `deploy/secrets/` (git-ignored), not environment values: `sh deploy/init-secrets.sh`.

## 3. Start

```bash
docker compose up -d --build          # first build takes several minutes
docker compose ps                     # app and caddy should both be "healthy"
```

Create the first organisation and owner (the password is read from the environment or prompted):

```bash
docker compose exec -e ACRETIA_OWNER_PASSWORD='choose-a-long-passphrase' app \
  python -m om.api create-org --data /data/app --name "Your Firm" --email you@yourfirm.com
```

Browse to `https://<ACRETIA_DOMAIN>/`.

### TLS: domain vs local

- **Public domain:** `ACRETIA_DOMAIN=acretia.example.com`, `ACRETIA_TLS=ops@example.com`. Caddy obtains and renews a Let's Encrypt certificate (stored in the `caddy_data` volume; do not delete it, ACME rate limits apply).
- **Local / LAN:** leave the defaults (`localhost`, `internal`). Caddy issues certificates from its own CA. Trust it once with `docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt` and add that file to your OS trust store, or accept the browser warning. Use `ACRETIA_HTTPS_PORT=8443` if 443 is busy, and browse `https://localhost:8443/`.

The app is never published: it has no `ports:`. Only Caddy listens on the host, and `app` trusts `X-Forwarded-*` only because nothing else can reach it.

### Rate limiting

Rate limiting is not in Caddy core. The app already throttles failed sign-ins per client (`om/api/security.py`). For per-IP request limits build Caddy with the MIT-licensed `github.com/mholt/caddy-ratelimit` module (`xcaddy build --with github.com/mholt/caddy-ratelimit`), swap it in as the `caddy` image, and add a `rate_limit` block to `deploy/Caddyfile`. Until then, put a network-level limiter (cloud WAF, `ufw limit`) in front.

## 4. Optional profiles

```bash
sh deploy/init-secrets.sh                              # once: random credentials in deploy/secrets/
docker compose --profile redis --profile postgres up -d
```

| Profile | Service | Licence | Wire-up |
|---|---|---|---|
| `redis` | Redis 7.2 (pinned, BSD) | BSD-3 | `ACRETIA_KV=redis`, `ACRETIA_REDIS_URL=redis://redis:6379/0` in `.env` |
| `postgres` | Postgres 16 | PostgreSQL | reachable as `postgres:5432`, database `acretia`, user `acretia`, password in `deploy/secrets/postgres_password` |
| `minio` | MinIO | **AGPL-3.0** | `ACRETIA_BLOB_BACKEND=s3`, `ACRETIA_S3_ENDPOINT=http://minio:9000`, `ACRETIA_S3_BUCKET=acretia`, `ACRETIA_S3_ACCESS_KEY`/`ACRETIA_S3_SECRET_KEY` from the secret files |

MinIO has no default image on purpose. Choose a release, resolve its digest, and set it in `.env`:

```bash
docker pull quay.io/minio/minio:RELEASE.<date>
echo "MINIO_IMAGE=$(docker inspect --format '{{index .RepoDigests 0}}' quay.io/minio/minio:RELEASE.<date>)" >> .env
```

The `data` network is `internal: true`: these stores have no route to the internet or the host.

### GPL / AGPL isolation (D-S1-01)

- Copyleft or restricted-weights software runs **only as a separate container** on the `data` network and is called over HTTP/S3. It is never imported, linked or copied into the `app` image. MinIO (AGPL) follows this. Marker and MinerU (restricted weights/terms) would get a `gpl-services` profile in the same way; none is shipped yet.
- `poppler` (GPL) and LibreOffice (MPL-2.0 with GPL parts) are installed in the app image but only ever executed as subprocesses (`pdftotext`, `pdftoppm`, `soffice`). Their packages and licences are the distribution's; source is available through `apt-get source`.
- PyMuPDF (AGPL) is not used.

### LibreOffice

LibreOffice recalculates workbooks and renders decks headless. The root filesystem is read-only, so `HOME=/tmp` and the profile lives in the `/tmp` tmpfs (1 GB, wiped on restart). The engines pass a per-run `-env:UserInstallation` profile directory. Fonts: DejaVu, Carlito (Calibri metrics) and Noto are installed so conversions are repeatable. If recalculation hangs, `docker compose restart app` clears stale profiles.

## 5. Backups

All state is in the `acretia_data` volume (`/data`): `app/acretia.db` (SQLite WAL), blobs, `secret.key`, the DuckDB grid store and the SEC cache. Also keep `caddy_data` (certificates).

```bash
sh deploy/backup.sh ./backups                         # stops app briefly, writes acretia-data-<UTC>.tar.gz
```

Restore into a stopped stack:

```bash
docker compose down
docker run --rm -v acretia_acretia_data:/data -v "$PWD/backups":/in alpine \
  sh -c 'rm -rf /data/* && tar xzf /in/acretia-data-<UTC>.tar.gz -C /data && chown -R 10001:10001 /data'
docker compose up -d
```

Copy backups off the host and encrypt them: they contain `secret.key`. If you use the `postgres` or `minio` profiles, back those volumes up too (`pg_dump`, `mc mirror`). Test a restore before you need one.

## 6. Upgrade

```bash
sh deploy/backup.sh ./backups
git pull
docker compose build --pull
docker compose up -d
docker compose ps                                     # wait for healthy
```

Schema migrations run automatically at app start. Rollback: check out the previous tag, rebuild, and restore the backup if a migration ran. Base images are pinned by digest; to bump one, pull the new tag, copy `docker inspect --format '{{index .RepoDigests 0}}'` into the `Dockerfile` ARG or `docker-compose.yml`, and re-run `python3 scripts/verify_s7_deploy.py`.

## 7. Hardening in place

`read_only: true` rootfs with tmpfs `/tmp`; non-root uid 10001; `cap_drop: [ALL]` (Caddy adds only `NET_BIND_SERVICE`); `no-new-privileges`; CPU, memory and PID limits; log rotation; healthchecks; no published app port; HSTS, CSP (`frame-ancestors 'none'`), `X-Content-Type-Options`, `Referrer-Policy` and `X-Frame-Options` on every response; digest-pinned images; no secrets in any image layer.

## 8. Sizing

| Load | vCPU / RAM | Notes |
|---|---|---|
| Demo, 1-3 users | 2 / 4 GB | `ACRETIA_APP_MEM=4g`, `ACRETIA_WITH_EXTRAS=0` is enough |
| Team, 10-25 users, document grids | 4 / 8 GB | defaults; docling parsing and LibreOffice recalcs dominate memory |
| 50+ users or large data rooms | 8 / 16 GB, SSD | add the `redis` profile for the job queue; plan for multi-instance only after the revisit noted in D-002 (SQLite is single-node) |

Disk: image about 6-8 GB with extras (about 1.5 GB without), plus data (budget 2x the size of your ingested documents, since parsed text, thumbnails and indexes are stored alongside the originals).

## 9. Verify

```bash
python3 scripts/verify_s7_deploy.py                        # static checks
ACRETIA_DEPLOY_LIVE=1 python3 scripts/verify_s7_deploy.py  # builds and runs the stack on ports 18080/18443, then removes it
```

Behind a TLS-inspecting proxy, pass its CA to the build with `ACRETIA_BUILD_CA=/path/ca-bundle.crt` (used as a BuildKit secret; not stored in the image).
