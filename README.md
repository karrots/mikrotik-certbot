# mikrotik-certbot

A Certbot deploy-hook tool that uploads renewed Let’s Encrypt certificates to MikroTik RouterOS devices and applies them to services. It is idempotent and non‑destructive: imports under a versioned name, applies to targets, then prunes older unreferenced certificates.

## Contents
- [mikrotik-certbot](#mikrotik-certbot)
  - [Contents](#contents)
  - [Highlights](#highlights)
  - [Prerequisites](#prerequisites)
  - [Initial Setup (Certbot deploy hook)](#initial-setup-certbot-deploy-hook)
  - [Application Flow](#application-flow)
  - [More Documentation](#more-documentation)
  - [Developer Workflows](#developer-workflows)
  - [License \& Authors](#license--authors)

## Highlights
- Versioned, collision‑safe certificate naming (UTC `YYYYMMDDThhmm`, `_SEQ` suffix when needed)
- REST upload on RouterOS ≥ 7.17; SFTP fallback otherwise, then REST import
- Applies to `www-ssl`, `api-ssl`, and optional Hotspot profiles
- Strict gating (`MIKROTIK_DOMAIN` must be in `RENEWED_DOMAINS`), `DRY_RUN` support

## Prerequisites
- Python `3.11+` and `uv` installed
- Certbot on the host that renews the certificate
- MikroTik RouterOS reachable over HTTPS (REST); SFTP enabled only if supporting fallback
- A RouterOS user with access to files/certificates/services

## Initial Setup (Certbot deploy hook)
1) Install `uv` if needed: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2) Download the hook directly (no repository clone required). Replace the example URL with the raw file URL for this repo:

No repository clone required — download the hook directly:

```sh
sudo curl -fsSL "https://raw.githubusercontent.com/karrots/mikrotik-certbot/refs/heads/main/deploy-hook.sh" -o /etc/letsencrypt/renewal-hooks/deploy/mikrotik-certbot.sh
```
   - `MIKROTIK_DOMAIN`: your FQDN (must appear in `RENEWED_DOMAINS`)
   - `ROUTER_HOST`: e.g., `router.example.net:8443`
   - `ROUTER_USER` / `ROUTER_PASS`: least‑privilege credentials
4) Verify with a dry‑run: `sudo certbot renew --dry-run --deploy-hook /etc/letsencrypt/renewal-hooks/deploy/mikrotik-certbot.sh`
5) If multiple hosts need certificates duplicate the `deploy-hook.sh` as needed.

See `docs/config.md` for all configuration options and behavior toggles.

## Application Flow
The hook exits early unless `MIKROTIK_DOMAIN` is present in `RENEWED_DOMAINS`. It derives a versioned, collision‑safe certificate name and detects RouterOS capabilities to pick REST upload or SFTP fallback. The combined PEM (privkey + fullchain) is uploaded, then imported without removing any existing same‑name certificate first. The new certificate is applied to `www-ssl`, `api-ssl`, and any configured Hotspot profiles. After a real import completes, older unreferenced certificates are pruned, keeping the newest two.

## More Documentation
- Configuration: `docs/config.md`
- Usage: `docs/usage.md`
- RouterOS Permissions: `docs/permissions.md`

## Developer Workflows
- Sync dev deps: `uv sync --group dev`
- Run: `uv run mikrotik-certbot`
- Lint: `uv run --group dev ruff check .`
- Types: `uv run --group dev mypy .`
- Tests: `uv run --group dev pytest`
- Build: `uv build`

## License & Authors
- License: MIT (see `LICENSE`)
- Author: Jonathan Karras
