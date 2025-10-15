# AI Assistant Instructions – mikrotik-certbot

Concise, project-specific guidance for automated coding agents. Focus on preserving current behaviors (idempotent, non-destructive certificate handling) and env‑driven configuration.

## 1. Purpose & Flow
Automates deployment of a renewed Let's Encrypt cert to MikroTik RouterOS:
1. Gate: skip unless `MIKROTIK_DOMAIN` is in `RENEWED_DOMAINS`.
2. Determine versioned cert name (timestamped; collision-safe).
3. Detect RouterOS version (>=7.17 enables REST `/file/add type=file`, else SFTP fallback then REST import).
4. Upload combined PEM (privkey + fullchain) -> remote file.
5. Import certificate (never delete existing prior to import).
6. Apply to `www-ssl`, `api-ssl`, and optional Hotspot profiles.
7. Prune older, unreferenced certs (retain newest 2) only if an import occurred.

## 2. Key Modules & Responsibilities
- `mikrotik_certbot/__main__.py`: CLI entrypoint, exception -> exit code mapping.
- `mikrotik_certbot/config.py`: Environment parsing (`load_settings`), explicit validation of `RENEWED_LINEAGE`, boolean parsing, hotspot profile normalization.
- `mikrotik_certbot/certificates.py`: Name/timestamp formatting, serial extraction, PEM combination.
- `mikrotik_certbot/routeros.py`: REST + SFTP operations, upload/import, pruning, service/profile updates, debug logging.
- `mikrotik_certbot/workflow.py`: Orchestration (collision handling, skip logic, conditional pruning).
- `deploy-hook.sh`: Certbot integration path selection (local project vs script dir vs `uvx --from SPEC`).

## 3. Naming & Collision Rules
Canonical: `domain.tld` -> `domain_tld_YYYYMMDDThhmm` (UTC). Override via `CERT_NAME`:
- Already versioned (`_YYYYMMDDThhmm[... ]`): use as-is.
- Legacy suffix `_YYYYMM`: replaced with current timestamp.
- Bare override: timestamp appended.
Collision (existing different-serial name): append `_SEQ` where `SEQ` = last 6 hex chars of local serial; if still collides append `_SEQ_1`, `_SEQ_2`, ...
Identical serial detection (by name or global serial scan) skips upload/import unless `FORCE_REIMPORT=1`.

## 4. Pruning Logic
Runs only after a real import (not dry-run, not skipped). Patterns recognised:
- Versioned: `base_YYYYMMDDThhmm(_SEQ)?(_n)?`
- Legacy: `base_YYYYMM`
Retention: keep newest 2 (hardcoded `keep=2`). Skips deletion if cert referenced by any `ip/service` or `ip/hotspot/profile`.

## 5. Environment-Driven Config (selected)
Required: `RENEWED_LINEAGE` (must contain `privkey.pem`, `fullchain.pem`).
Gate: `RENEWED_DOMAINS` space-separated list; must include `MIKROTIK_DOMAIN`.
Security: `VERIFY_SSL`, `SFTP_AUTO_ACCEPT_HOST_KEY` (default true), least-privilege RouterOS user.
Behavior toggles: `UPDATE_WWW_SSL`, `UPDATE_API_SSL`, `DRY_RUN`, `FORCE_REIMPORT`, `KEEP_UPLOADED_FILE`, `OVERWRITE` (file re-upload), `FULL_HTTP_DEBUG`, `HTTP_DEBUG_BODY_LIMIT`.
Hotspot: `HOTSPOT_PROFILE_NAMES` (comma/space/semicolon or quoted tokens).
Naming: `CERT_NAME` optional override.

## 6. Debug & Safety Patterns
- Never proactively delete same-name cert pre-import (`remove_old_certificate` only logs).
- Debug HTTP summaries gated by `DEBUG`; extended bodies by `FULL_HTTP_DEBUG` with size limit & private key redaction.
- Dry run still reads files (existence validation) but skips network mutations.
- SFTP host key acceptance is configurable (`SFTP_AUTO_ACCEPT_HOST_KEY`).

## 7. Developer Workflows
Using uv:
- Run: `uv run mikrotik-certbot`
- Lint: `uv run --group dev ruff check .`
- Types: `uv run --group dev mypy .`
- Tests: `uv run --group dev pytest`
- Build: `uv build`
Test focus areas: naming (`tests/test_naming.py`), pruning (`tests/test_prune.py`), collision/import logic (`tests/test_collision_and_import.py`).

## 8. Extension Guidelines
When adding features:
- Respect gating & dry-run semantics (no state change when `dry_run` true).
- Keep certificate naming backward compatible; add regex in pruning if new suffixes introduced.
- Add env var parsing in `config.py` (validate aggressively) and include in docs.
- Reuse `RouterOSClient.debug_http` for new endpoints.

## 9. Common Pitfalls to Avoid
- Skipping the domain gate (must guard early in `run`).
- Pruning when no import occurred (maintain current conditional).
- Introducing unbounded REST output logging (respect body limit & redaction rules).
- Altering timestamp format (tests depend on `YYYYMMDDThhmm`).

## 10. Example Dry Run
```
DRY_RUN=1 MIKROTIK_DOMAIN=example.com RENEWED_DOMAINS="example.com" \
RENEWED_LINEAGE=/etc/letsencrypt/live/example.com \
ROUTER_HOST=router:8443 ROUTER_USER=certbot ROUTER_PASS=secret \
uv run mikrotik-certbot
```

---
Provide feedback if any missing nuance (e.g. additional pruning patterns, error handling expectations) should be added.
