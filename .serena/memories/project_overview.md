Purpose: Certbot deploy-hook tool that uploads renewed Let’s Encrypt certificates to MikroTik RouterOS via REST (with SFTP fallback), applies to services, and prunes old certs in an idempotent, non-destructive way.
Tech stack: Python 3.11+, packaging via PEP 517/621 (pyproject.toml) using Hatchling backend. Runtime deps: requests, paramiko (cryptography used in code). Dev tools: uv, ruff, mypy, pytest.
Repo structure: pyproject.toml, main.py CLI wrapper, package 'mikrotik_certbot' (config, certificates, routeros, workflow), tests/, docs/, deploy-hook.sh. Entry point is configured under [project.scripts].
Conventions: Type hints throughout, ruff line-length=120, mypy configured with strict warnings. DEBUG/DRY_RUN env flags control behavior.
Behavior: Gated by RENEWED_DOMAINS + MIKROTIK_DOMAIN; versioned certificate naming; safe import; apply to services/hotspot; prune after import.
Notes: Console-script should point into package; ensure all runtime imports (e.g., cryptography) are declared as dependencies.
