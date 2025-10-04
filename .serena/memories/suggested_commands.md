Run CLI locally: `uv run mikrotik-certbot` (or `uv run main.py`).
Dry run example: `DRY_RUN=1 MIKROTIK_DOMAIN=example.com RENEWED_DOMAINS="example.com" RENEWED_LINEAGE=/etc/letsencrypt/live/example.com ROUTER_HOST=router:8443 ROUTER_USER=certbot ROUTER_PASS=secret uv run mikrotik-certbot`.
Lint: `uv run --with dev ruff check .`
Type check: `uv run --with dev mypy .`
Tests: `uv run --with dev pytest`.
Build (if using hatch): `uv run -m hatch build` (ensure pyproject.hatch config correct).