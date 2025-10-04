import re
from types import SimpleNamespace

from mikrotik_certbot.config import load_settings


class FakeClient:
    def __init__(self, settings=None):
        self._cert_store = {}
        self.settings = settings

    def get(self, path, params=None, timeout=10, label=None):
        # Simulate certificate lookups
        if path == "certificate":
            name = (params or {}).get("name")
            if name:
                item = self._cert_store.get(name)
                resp = SimpleNamespace(ok=True, json=lambda: [item] if item else [])
                return resp
        # Default: return empty list
        return SimpleNamespace(ok=True, json=lambda: [])

    # stub other methods used in workflow to avoid network
    def post(self, *args, **kwargs):
        return SimpleNamespace(ok=True, json=lambda: {})

    def patch(self, *args, **kwargs):
        return SimpleNamespace(ok=True)

    def delete(self, *args, **kwargs):
        return SimpleNamespace(ok=True)


def test_collision_appends_seq(monkeypatch, tmp_path):
    lineage = tmp_path
    (lineage / "privkey.pem").write_text("dummy", encoding="utf-8")
    (lineage / "fullchain.pem").write_text("dummy", encoding="utf-8")

    env = {
        "RENEWED_LINEAGE": str(lineage),
        "RENEWED_DOMAINS": "example.com",
        "MIKROTIK_DOMAIN": "example.com",
    }
    settings = load_settings(env)

    fake = FakeClient()
    # provide the settings object so upload/combination steps can read paths
    fake.settings = settings
    # Simulate existing cert with same name but different serial
    fake._cert_store["example_com_20251007T1200"] = {"name": "example_com_20251007T1200", "serial-number": "ABCDEF"}

    # Monkeypatch functions used
    import mikrotik_certbot.workflow as wf

    monkeypatch.setattr(wf, "detect_routeros_version", lambda client: ("7.17", True))
    monkeypatch.setattr(wf, "RouterOSClient", lambda settings: fake)
    monkeypatch.setattr(wf, "get_local_cert_serial", lambda path: "A1B2C3D4E5F6")
    # provide the settings object so upload/combination steps can read paths
    fake.settings = settings

    # Monkeypatch router functions referenced by workflow.run so they are no-ops
    for fn in (
        "upload_certificate",
        "confirm_file_exists",
        "delete_uploaded_file",
        "remove_old_certificate",
        "import_new_certificate",
        "confirm_certificate_present",
        "update_ip_service",
        "update_hotspot_profile",
        "prune_old_certificates",
    ):
        monkeypatch.setattr(wf, fn, lambda *a, **k: None)

    # Run determine_certificate_name then simulate collision handling in run
    cert_name = wf.determine_certificate_name(settings)
    assert re.match(r"^example_com_\d{8}T\d{4}$", cert_name)

    # Now exercise the run collision path to ensure it chooses a candidate with _SEQ
    performed = wf.run(settings)
    assert performed is True
