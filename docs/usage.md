# Usage

This tool is typically invoked by Certbot via a deploy hook after renewal, but it can also be run manually for testing.

## Install prerequisites

Use `uv` for running without a local virtualenv. Install if missing:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## CLI execution

From a local clone:

```bash
uv sync
uv run mikrotik-certbot
```

No local repo (PyPI via uvx):

```bash
# Run the console script directly from PyPI without cloning
uvx --from mikrotik-certbot mikrotik-certbot

# Example dry run from PyPI
DRY_RUN=1 MIKROTIK_DOMAIN=example.com ROUTER_HOST=router.local \
  ROUTER_USER=certbot ROUTER_PASS='secret' \
  RENEWED_LINEAGE=/etc/letsencrypt/live/example.com \
  RENEWED_DOMAINS="example.com" \
  uvx --from mikrotik-certbot mikrotik-certbot

# Pin a specific version from PyPI
uvx --from 'mikrotik-certbot==1.0.0' mikrotik-certbot
```

Dry run (no changes):

```bash
DRY_RUN=1 MIKROTIK_DOMAIN=example.com ROUTER_HOST=router.local \
  ROUTER_USER=certbot ROUTER_PASS='secret' \
  RENEWED_LINEAGE=/etc/letsencrypt/live/example.com \
  RENEWED_DOMAINS="example.com" \
  uv run mikrotik-certbot
```

## Certbot integration via deploy hook

Copy the provided hook:

```bash
sudo cp deploy-hook.sh /etc/letsencrypt/renewal-hooks/deploy/mikrotik-certbot.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/mikrotik-certbot.sh
```

How `deploy-hook.sh` finds the code (auto‑detected in order):
- `PROJECT_ROOT` points to a clone containing `pyproject.toml` → runs `uv run mikrotik-certbot` there.
- The script resides in the project root → runs from that directory.
- Fallback: `uvx --from "$MIKROTIK_CERTBOT_SPEC" mikrotik-certbot` (defaults to PyPI package name).

Pin a specific version or Git ref:

```bash
sudo MIKROTIK_CERTBOT_SPEC='mikrotik-certbot==0.1.0' \
  /etc/letsencrypt/renewal-hooks/deploy/mikrotik-certbot.sh

sudo MIKROTIK_CERTBOT_SPEC='git+https://github.com/karrots/mikrotik-certbot@v0.1.0' \
  /etc/letsencrypt/renewal-hooks/deploy/mikrotik-certbot.sh
```

Verify Certbot integration safely:

```bash
sudo certbot renew --dry-run --deploy-hook /etc/letsencrypt/renewal-hooks/deploy/mikrotik-certbot.sh
```

Manual one‑off test (outside Certbot):

```bash
sudo RENEWED_DOMAINS=example.com MIKROTIK_DOMAIN=example.com \
  ROUTER_USER=certbot ROUTER_PASS='REDACTED' ROUTER_HOST=router.example.net:8443 \
  RENEWED_LINEAGE=/etc/letsencrypt/live/example.com \
  /etc/letsencrypt/renewal-hooks/deploy/mikrotik-certbot.sh
```

The hook gates execution: it exits with a message if `MIKROTIK_DOMAIN` is not present in `RENEWED_DOMAINS`.

## Service update order

When enabled, the workflow updates `www-ssl` first over a single SSH connection: disable the service, assign the new certificate, wait 2 seconds, then re-enable it. This avoids changing the certificate on a live HTTPS listener and deliberately interrupts HTTPS/REST briefly. SSH must be reachable on port 22, even on routers that support REST uploads. If assignment fails, the router-side script attempts to re-enable the service and the run fails.

After SSH confirms the binding, the tool waits `WWW_SSL_SETTLE_SECONDS` seconds (default: 5), probes REST readiness, and only then updates Hotspot profiles and `api-ssl`. If all readiness probes fail, it uses SSH to disable and re-enable only `www-ssl` once, then immediately repeats the REST probes. If the SSH update fails or REST still does not recover, the run stops before any remaining bindings or pruning are changed. Existing certificates are retained; the tool does not automatically roll back the certificate binding.

## RouterOS version detection and SFTP fallback

At runtime the tool queries RouterOS to decide the upload strategy:
- If version ≥ 7.17: `POST /rest/file/add` with `{ type: "file" }` is used.
- If version < 7.17 or detection fails: uploads via SFTP (port 22), then imports via REST.

SFTP notes:
- Requires the RouterOS SSH service and a user permitted to write files.
- Only the host part of `ROUTER_HOST` is used for SSH; port is fixed at 22.
- Host key acceptance is controlled by `SFTP_AUTO_ACCEPT_HOST_KEY` (default: true).

The `www-ssl` SSH update and recovery use the same port, credentials, and host-key setting. They require `ssh` and `write`; `ftp` is only required when SFTP upload fallback is used.

## Logging and debugging

Tunable verbosity is available:
- `DEBUG=1` prints HTTP summaries for REST calls.
- `FULL_HTTP_DEBUG=1` includes response bodies, redacting private keys and limited to `HTTP_DEBUG_BODY_LIMIT` characters.

## Naming and pruning overview

Imports under a versioned, collision‑safe name (UTC `YYYYMMDDThhmm`; `_SEQ` suffix on collision). If an identical serial already exists, import is skipped unless `FORCE_REIMPORT=1`. After a successful import (not dry‑run), the tool prunes older unreferenced certificates, keeping the newest 2. See `docs/config.md` for full details and environment variables.
