#!/usr/bin/env python3
"""S7.5b deployment gate: static checks of Dockerfile / compose / Caddyfile, plus an optional live stack test.

Static checks always run. The live test runs only with ACRETIA_DEPLOY_LIVE=1 and a working docker CLI + daemon:
build, `docker compose up -d`, wait for health, request the health endpoint and the frontend index through Caddy
(https, local CA, `-k` is allowed here only for that local CA), check security headers, `docker compose down -v`.
Prints PASS/FAIL/SKIP rows; exits non-zero on any FAIL.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ROWS: list[tuple[str, str, str]] = []
FILES = ["Dockerfile", ".dockerignore", "docker-compose.yml", "deploy/Caddyfile", "DEPLOY.md",
         "deploy/init-secrets.sh", "deploy/backup.sh", "scripts/verify_s7_deploy.py"]


def row(status: str, name: str, detail: str = "") -> None:
    ROWS.append((status, name, detail))
    print(f"{status:<5} {name}" + (f"  -- {detail}" if detail else ""), flush=True)


def check(name: str, ok: bool, detail: str = "") -> None:
    row("PASS" if ok else "FAIL", name, "" if ok else detail)


def sh(args, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, **kw)


def images_of(compose: dict) -> list[str]:
    return [s["image"] for s in compose["services"].values() if "image" in s]


def static_checks() -> None:
    for f in FILES:
        check(f"file present: {f}", (ROOT / f).is_file(), "missing")
    df = (ROOT / "Dockerfile").read_text()
    dc = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    caddy = (ROOT / "deploy/Caddyfile").read_text()
    services = dc["services"]

    # --- Dockerfile
    users = re.findall(r"^USER\s+(\S+)", df, re.M)
    check("Dockerfile: final USER is non-root", bool(users) and users[-1].split(":")[0] not in ("root", "0"),
          f"USER lines: {users}")
    check("Dockerfile: USER uid 10001", bool(users) and users[-1].startswith("10001"), f"USER lines: {users}")
    froms = re.findall(r"^FROM\s+(\S+)", df, re.M)
    check("Dockerfile: multi-stage", len(froms) >= 2, f"FROM: {froms}")
    args = dict(re.findall(r"^ARG\s+(\w+_IMAGE)=(\S+)", df, re.M))
    refs = [args.get(f[2:-1], f) if f.startswith("${") else f for f in froms]
    refs = [r for r in refs if r != "scratch"]
    check("Dockerfile: base images pinned by sha256 digest", all(re.search(r"@sha256:[0-9a-f]{64}$", r) for r in refs),
          f"unpinned: {[r for r in refs if '@sha256:' not in r]}")
    check("Dockerfile: no 'latest' tag", not any(r.endswith(":latest") or ":" not in r.split("@")[0] for r in refs),
          f"refs: {refs}")
    check("Dockerfile: HEALTHCHECK", "HEALTHCHECK" in df)
    check("Dockerfile: PYTHONDONTWRITEBYTECODE", "PYTHONDONTWRITEBYTECODE=1" in df)
    check("Dockerfile: binds 0.0.0.0", "--host 0.0.0.0" in df)
    check("Dockerfile: base is python:3.12-slim", any(r.startswith("python:3.12-slim") for r in refs), f"{refs}")
    for pkg in ("libreoffice-calc", "libreoffice-impress", "poppler-utils", "tesseract-ocr", "tesseract-ocr-ara",
                "fonts-dejavu-core", "fonts-crosextra-carlito", "fonts-noto-core"):
        check(f"Dockerfile: apt package {pkg}", re.search(rf"\b{re.escape(pkg)}\b", df) is not None)
    check("Dockerfile: HOME under /tmp (LibreOffice profile)", re.search(r"HOME=/tmp\b", df) is not None)
    check("Dockerfile: no secret-bearing ENV/ARG",
          not re.search(r"(?im)^\s*(ENV|ARG)\s+\w*(KEY|SECRET|TOKEN|PASSWORD)\w*\s*=\s*\S+", df), "secret-like ENV/ARG with a value")
    check("Dockerfile: no COPY of .env", not re.search(r"(?m)^COPY\b.*\.env\b", df))
    di = (ROOT / ".dockerignore").read_text().split()
    check(".dockerignore: excludes .env, .git, data", all(x in di for x in (".env", ".git", "data")), f"{di[:10]}")

    # --- compose
    for img in images_of(dc):
        img = re.sub(r"^\$\{\w+:-(.*)\}$", r"\1", img)  # image given as ${VAR:-default}: check the default
        base = img.split("@")[0]
        tag = base.split(":", 1)[1] if ":" in base.rsplit("/", 1)[-1] else ""
        if img.startswith("acretia/"):
            check(f"compose image {img}: local build, versioned tag", tag not in ("", "latest") or "${" in img, img)
            continue
        pinned = re.search(r"@sha256:[0-9a-f]{64}", img) is not None
        check(f"compose image {img[:60]}: no latest tag", tag != "latest" and (tag != "" or pinned), img)
        check(f"compose image {img[:60]}: digest pinned", re.search(r"@sha256:[0-9a-f]{64}", img) is not None, img)
    for name in ("app", "caddy"):
        check(f"compose: service {name} present", name in services)
    app, cdy = services["app"], services["caddy"]
    check("compose: app read_only", app.get("read_only") is True)
    check("compose: app tmpfs /tmp", any(str(t).startswith("/tmp") for t in app.get("tmpfs", [])))
    check("compose: app named volume at /data", any(str(v).endswith(":/data") and not str(v).startswith(("/", ".")) for v in app.get("volumes", [])))
    check("compose: app has no published ports", not app.get("ports"), f"{app.get('ports')}")
    check("compose: app depends only via caddy (caddy publishes 80/443)", bool(cdy.get("ports")))
    for name, svc in services.items():
        check(f"compose: {name} cap_drop ALL", "ALL" in [str(c).upper() for c in svc.get("cap_drop", [])])
        check(f"compose: {name} no-new-privileges", "no-new-privileges:true" in svc.get("security_opt", []))
        lim = svc.get("deploy", {}).get("resources", {}).get("limits", {})
        check(f"compose: {name} memory and cpu limits", "memory" in lim and "cpus" in lim, f"{lim}")
        check(f"compose: {name} healthcheck", "healthcheck" in svc)
        check(f"compose: {name} not privileged / host network", not svc.get("privileged") and svc.get("network_mode") != "host")
        if name != "app":
            check(f"compose: {name} published ports only on caddy", name == "caddy" or not svc.get("ports"))
    check("compose: optional profiles postgres/redis/minio",
          all(services.get(p, {}).get("profiles") == [p] for p in ("postgres", "redis", "minio")))
    check("compose: redis pinned to 7.2", services["redis"]["image"].startswith("redis:7.2"))
    check("compose: env_file .env optional",
          any(isinstance(e, dict) and e.get("path") == ".env" and e.get("required") is False for e in app.get("env_file", [])))
    check("compose: store credentials via secrets files, not env values",
          all("PASSWORD_FILE" in json.dumps(services[s].get("environment", {})) for s in ("postgres", "minio")))
    check("compose: data network is internal", dc["networks"]["data"].get("internal") is True)

    # --- Caddy
    for hdr in ("Strict-Transport-Security", "Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy"):
        check(f"Caddyfile: header {hdr}", hdr in caddy)
    check("Caddyfile: frame-ancestors none", "frame-ancestors 'none'" in caddy)
    check("Caddyfile: HSTS max-age >= 1 year", (m := re.search(r"max-age=(\d+)", caddy)) is not None and int(m.group(1)) >= 31536000)
    check("Caddyfile: proxies to app:8791", "reverse_proxy app:8791" in caddy)
    check("Caddyfile: SSE not buffered", "flush_interval -1" in caddy)
    check("Caddyfile: tls internal default", "{$ACRETIA_TLS:internal}" in caddy)
    row("SKIP", "Caddy rate limiting", "not in Caddy core; documented in DEPLOY.md (caddy-ratelimit plugin) + app sign-in throttle")
    check("DEPLOY.md documents rate limiting", "rate limit" in (ROOT / "DEPLOY.md").read_text().lower())

    # --- secrets
    scan = sh([sys.executable, "scripts/secret_scan.py", *[f for f in FILES if (ROOT / f).is_file()]])
    check("secret_scan.py clean on deployment files", scan.returncode == 0, (scan.stdout + scan.stderr).strip()[:400])
    leaked = [str(p.relative_to(ROOT)) for p in (ROOT / "deploy/secrets").glob("*") if p.name not in (".gitignore", "README")]
    tracked = sh(["git", "ls-files", "deploy/secrets"]).stdout.split()
    check("no secret files tracked in deploy/secrets", all(Path(t).name in (".gitignore", "README") for t in tracked), f"{tracked} {leaked}")
    cfg = sh(["docker", "compose", "config", "-q"]) if shutil.which("docker") else None
    if cfg is None:
        row("SKIP", "docker compose config validates", "docker CLI not found")
    else:
        check("docker compose config validates", cfg.returncode == 0, cfg.stderr.strip()[:300])


# ---------------------------------------------------------------------------- live
def docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    return sh(["docker", "info"]).returncode == 0


def fetch(path: str, host: str, port: int = 18443, sni: str = "localhost") -> tuple[int, dict, bytes]:
    """HTTPS GET to 127.0.0.1:<port> with SNI/Host `host`. Certificate verification is off: the cert comes from
    Caddy's local CA (`tls internal`), which is not in the trust store. Gate-only."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    name = sni
    conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=15, context=ctx)
    conn.connect = lambda: _connect(conn, ctx, name, port)  # type: ignore[method-assign]
    try:
        conn.request("GET", path, headers={"Host": host, "Accept-Encoding": "identity"})
        r = conn.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        conn.close()


def _connect(conn, ctx, sni: str, port: int) -> None:
    import socket
    sock = socket.create_connection(("127.0.0.1", port), timeout=15)
    conn.sock = ctx.wrap_socket(sock, server_hostname=sni)


def live_checks() -> None:
    if os.environ.get("ACRETIA_DEPLOY_LIVE") != "1":
        row("SKIP", "live stack test", "set ACRETIA_DEPLOY_LIVE=1 to build and run the stack")
        return
    if not docker_ok():
        row("SKIP", "live stack test", "docker CLI or daemon unavailable")
        return
    env = dict(os.environ, ACRETIA_HTTP_PORT="18080", ACRETIA_HTTPS_PORT="18443", ACRETIA_DOMAIN="localhost",
               ACRETIA_VERSION="gate", COMPOSE_PROJECT_NAME="acretia_gate")
    env.pop("MINIO_IMAGE", None)
    compose = ["docker", "compose", "-p", "acretia_gate"]
    t0 = time.time()
    try:
        cmd = ["docker", "build", "-t", "acretia/app:gate", "--build-arg", f"WITH_EXTRAS={os.environ.get('ACRETIA_WITH_EXTRAS', '1')}"]
        if os.environ.get("ACRETIA_BUILD_CA"):  # CA bundle for builds behind a TLS-inspecting proxy (BuildKit secret, not stored)
            cmd += ["--secret", f"id=cabundle,src={os.environ['ACRETIA_BUILD_CA']}"]
        b = subprocess.run(cmd + ["."], cwd=ROOT, env=env, capture_output=True, text=True)
        check("live: image builds", b.returncode == 0, b.stderr[-800:])
        if b.returncode != 0:
            return
        row("PASS", "live: build time", f"{time.time() - t0:.0f}s")
        size = sh(["docker", "image", "inspect", "acretia/app:gate", "--format", "{{.Size}}"]).stdout.strip()
        row("PASS", "live: image size", f"{int(size) / 1e9:.2f} GB" if size.isdigit() else size)
        up = subprocess.run(compose + ["up", "-d", "--wait", "--wait-timeout", "240"], cwd=ROOT, env=env,
                            capture_output=True, text=True)
        check("live: stack up and healthy", up.returncode == 0, (up.stdout + up.stderr)[-800:])
        if up.returncode != 0:
            logs = subprocess.run(compose + ["logs", "--tail", "40"], cwd=ROOT, env=env, capture_output=True, text=True)
            print(logs.stdout[-2500:])
            return
        ps = json.loads("[" + ",".join(subprocess.run(compose + ["ps", "--format", "json"], cwd=ROOT, env=env,
                                                      capture_output=True, text=True).stdout.strip().splitlines()) + "]")
        check("live: app and caddy healthy", {p["Service"]: p.get("Health") for p in ps} == {"app": "healthy", "caddy": "healthy"}, str(ps)[:300])
        app_ports = [p for p in ps if p["Service"] == "app"][0].get("Publishers") or []
        check("live: app publishes no host port", not any(p.get("PublishedPort") for p in app_ports), str(app_ports))
        st, h, body = fetch("/api/v1/healthz", "localhost:18443")
        check("live: GET /api/v1/healthz via caddy -> 200 ok", st == 200 and json.loads(body).get("ok") is True, f"{st} {body[:200]!r}")
        check("live: HSTS", "max-age=" in h.get("strict-transport-security", ""), str(h))
        check("live: X-Content-Type-Options nosniff", h.get("x-content-type-options") == "nosniff", str(h))
        check("live: Referrer-Policy", bool(h.get("referrer-policy")), str(h))
        check("live: CSP with frame-ancestors 'none'", "frame-ancestors 'none'" in h.get("content-security-policy", ""), str(h))
        check("live: X-Frame-Options DENY", h.get("x-frame-options") == "DENY", str(h))
        check("live: Server header removed", "server" not in h, str(h))
        st, h, body = fetch("/", "localhost:18443")
        check("live: frontend index served (200, html, app root)", st == 200 and b"<div id=\"root\"" in body and "text/html" in h.get("content-type", ""),
              f"{st} {h.get('content-type')} {body[:120]!r}")
        st, _, _ = fetch("/some/spa/route", "localhost:18443")
        check("live: SPA fallback on unknown route", st == 200, str(st))
        st, _, _ = fetch("/api/v1/healthz", "evil.example")  # right SNI, wrong Host: the app host guard must refuse
        check("live: foreign Host header refused", st in (403, 421), str(st))
        r = subprocess.run(["docker", "exec", "acretia_gate-app-1", "sh", "-c", "touch /app/x 2>&1; id -u"], capture_output=True, text=True)
        check("live: app runs as uid 10001 on read-only rootfs", r.stdout.strip().endswith("10001") and "Read-only" in r.stdout, r.stdout + r.stderr)
        r = subprocess.run(["docker", "exec", "acretia_gate-app-1", "sh", "-c", "touch /data/.w && echo ok"], capture_output=True, text=True)
        check("live: /data writable by app", "ok" in r.stdout, r.stdout + r.stderr)
        r = subprocess.run(["docker", "exec", "acretia_gate-app-1", "sh", "-c", "soffice --version && pdftotext -v 2>&1 | head -1 && tesseract --list-langs | grep -c ara"],
                           capture_output=True, text=True)
        check("live: soffice, pdftotext, tesseract(ara) present", r.returncode == 0, r.stdout + r.stderr)
    finally:
        d = subprocess.run(compose + ["down", "-v", "--remove-orphans"], cwd=ROOT, env=env, capture_output=True, text=True)
        check("live: docker compose down -v", d.returncode == 0, d.stderr[-300:])
        sh(["docker", "image", "rm", "-f", "acretia/app:gate"])


def main() -> int:
    static_checks()
    try:
        live_checks()
    except Exception as e:  # a crash in the live phase is a failure, never a silent pass
        row("FAIL", "live: unexpected error", f"{type(e).__name__}: {e}")
    n = {k: sum(1 for r in ROWS if r[0] == k) for k in ("PASS", "FAIL", "SKIP")}
    print(f"\n{n['PASS']} PASS, {n['FAIL']} FAIL, {n['SKIP']} SKIP  ({n['PASS']}/{n['PASS'] + n['FAIL']} checks passed)")
    return 1 if n["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
