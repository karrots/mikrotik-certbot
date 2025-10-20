# Configuration

This project is configured entirely via environment variables. Values are parsed at runtime; no files are written or modified. Booleans accept any of: `1`, `true`, `yes`, `on` (case‑insensitive). Defaults are shown in parentheses.

## Required
- `MIKROTIK_DOMAIN` (default `your.domain.com`): Target domain that must appear in `RENEWED_DOMAINS` or the run is skipped.

## RouterOS connection
- `ROUTER_HOST` (default `192.168.88.1:443`): Hostname or IP and optional port of the RouterOS REST API endpoint.
- `ROUTER_USER` (default `api-user`): RouterOS username with least privileges for files/certificates/services.
- `ROUTER_PASS` (default `your-password`): RouterOS user password.
- `VERIFY_SSL` (default `false`): Verify the router’s HTTPS certificate.

## Behavior toggles
- `DRY_RUN` (default `false`): Perform validation and logging but do not mutate the router.
- `FORCE_REIMPORT` (default `false`): Re‑import even if an identical serial already exists on the router.
- `UPDATE_WWW_SSL` (default `true`): Apply the imported certificate to the `www-ssl` service.
- `UPDATE_API_SSL` (default `true`): Apply the imported certificate to the `api-ssl` service.
- `HOTSPOT_PROFILE_NAMES` (default empty): One or more Hotspot profiles to update. Accepts comma/space/semicolon, or quoted tokens (e.g., `default, login` or `"My Profile"`).
- `CERT_NAME` (optional): Override base certificate name. If already versioned (e.g., `_YYYYMMDDThhmm...`), used as‑is; legacy `_YYYYMM` is normalized; otherwise a current timestamp is appended.
- `KEEP_UPLOADED_FILE` (default `false`): Keep the uploaded PEM file after import.
- `OVERWRITE` (default `true`): When using REST upload, delete and re‑upload if the remote file already exists.
- `DEBUG` (default `false`): Enable concise HTTP summaries for REST calls.
- `FULL_HTTP_DEBUG` (default `false`): Include response bodies with redaction and size limiting.
- `HTTP_DEBUG_BODY_LIMIT` (default `2000`): Max characters of body to print when `FULL_HTTP_DEBUG=1`.
- `SFTP_AUTO_ACCEPT_HOST_KEY` (default `true`): For SFTP fallback, automatically accept unknown SSH host keys. Set to `false` to enforce host key verification.

## Internal Usage
The below environment variables are provided by Certbot at run time. If manually testing script without Certbot, dummy data will need to be provided.
- `RENEWED_LINEAGE` (Provided by Certbot): Absolute path to the renewed lineage directory provided by Certbot, and must contain `privkey.pem` and `fullchain.pem`.
- `RENEWED_DOMAINS` (Provided by Certbot): Space‑separated domains for the renewed certificate (from Certbot). Used for gating.

## Name/collision rules (reference)
- Canonical: `domain.tld` → `domain_tld_YYYYMMDDThhmm` (UTC). Collisions append `_SEQ` (last 6 hex chars of the local serial), then `_1`, `_2`, … if needed.
- If an identical serial already exists (by name or global serial scan), upload/import is skipped unless `FORCE_REIMPORT=1`.

## Pruning (reference)
- Runs only after a real import (not dry‑run, not skipped).
- Recognized patterns: `base_YYYYMMDDThhmm(_SEQ)?(_n)?` and legacy `base_YYYYMM`.
- Retains newest 2 certificates and skips any referenced by `ip/service` or `ip/hotspot/profile`.

## deploy-hook.sh (integration helpers)
These variables are used by the optional Certbot deploy hook wrapper:
- `PROJECT_ROOT` (optional): If set to a local clone with `pyproject.toml`, runs that project via `uv run`.
- `MIKROTIK_CERTBOT_SPEC` (default `mikrotik-certbot`): `uvx --from` spec (PyPI or Git) to execute when no local project is found.
- `UVX_REFRESH` (default `0`): Set `1` (or `true`) to add `--refresh` for `uvx`.
- `LE_BASE_PATH` (optional, not used by Python): Base path to Let’s Encrypt live directories if your layout differs; primarily for shell convenience.

Tip: For security, prefer least‑privilege RouterOS credentials and enable `VERIFY_SSL` when the router trusts a known CA.

