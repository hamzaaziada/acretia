#!/bin/sh
# Back up the /data volume (SQLite DB, blobs, secret.key) to ./backups/acretia-data-<UTC>.tar.gz.
# SQLite is online-backed-up with .backup semantics via a brief app stop for a fully consistent copy.
set -eu
out="${1:-./backups}"; mkdir -p "$out"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose stop app
trap 'docker compose start app' EXIT
docker run --rm -v acretia_acretia_data:/data:ro -v "$(cd "$out" && pwd)":/out \
  --entrypoint tar "$(docker compose config --images | grep '^acretia/app')" czf "/out/acretia-data-$ts.tar.gz" -C /data .
echo "wrote $out/acretia-data-$ts.tar.gz"
