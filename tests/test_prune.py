from types import SimpleNamespace

from mikrotik_certbot.routeros import prune_old_certificates


class FakeClient:
    def __init__(self, certs, services=None, profiles=None):
        # certs: list of dicts representing router certificate entries
        self._certs = certs
        self._services = services or []
        self._profiles = profiles or []

    def get(self, path, params=None, timeout=10, label=None):
        def _resp(data):
            return SimpleNamespace(ok=True, json=lambda: data, raise_for_status=lambda: None)

        if path == "certificate":
            return _resp(self._certs)
        if path == "ip/service":
            return _resp(self._services)
        if path == "ip/hotspot/profile":
            return _resp(self._profiles)
        return _resp([])

    def delete(self, path, timeout=20):
        # Simulate successful delete
        return SimpleNamespace(ok=True)


def make_cert_entry(name, cid):
    return {"name": name, ".id": cid, "serial-number": "AA:BB:CC"}


def test_prune_dry_run_outputs_decision_list(capsys):
    domain = "example.com"
    current = "example_com_20251007T1200"
    certs = [
        make_cert_entry("example_com_20251007T1200", "1"),
        make_cert_entry("example_com_20251001T1200_A1B2C3", "2"),
        make_cert_entry("example_com_202501", "3"),
    ]
    client = FakeClient(certs)
    prune_old_certificates(client, domain, current, keep=2, dry_run=True)
    out = capsys.readouterr().out
    assert "DRY-RUN: Decision list" in out or "Decision list" in out
    assert "CURRENT-KEEP" in out


def test_prune_skips_referenced_certificates(capsys):
    domain = "example.com"
    current = "example_com_20251007T1200"
    certs = [
        make_cert_entry("example_com_20241001T0000", "10"),
    ]
    services = [{"name": "www-ssl", "certificate": "example_com_20241001T0000"}]
    client = FakeClient(certs, services=services)
    prune_old_certificates(client, domain, current, keep=0, dry_run=False)
    out = capsys.readouterr().out
    assert "Skipping deletion" in out or "Skipping" in out
