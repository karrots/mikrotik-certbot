from types import SimpleNamespace

import pytest
import requests

from mikrotik_certbot.config import load_settings
from mikrotik_certbot.routeros import update_hotspot_profile, update_ip_service


def _response(data):
    return SimpleNamespace(json=lambda: data, raise_for_status=lambda: None)


class RestartingServiceClient:
    def __init__(self, service_name="www-ssl"):
        self.service = {".id": "*4", "name": service_name, "certificate": "old_cert"}
        self.patch_calls = 0

    def get(self, path, params=None, timeout=10, label=None):
        assert path == "ip/service"
        assert (params or {}).get("name") == self.service["name"]
        return _response([self.service])

    def patch(self, path, json=None, timeout=15, label=None):
        assert path == "ip/service/*4"
        self.patch_calls += 1
        self.service["certificate"] = json["certificate"]
        raise requests.ConnectionError("connection reset by peer")


class RestartingHotspotClient:
    def __init__(self):
        self.profile = {".id": "*7", "name": "guest", "ssl-certificate": "old_cert"}
        self.patch_calls = 0

    def get(self, path, params=None, timeout=10, label=None):
        assert path == "ip/hotspot/profile"
        assert (params or {}).get("name") == "guest"
        return _response([self.profile])

    def patch(self, path, json=None, timeout=15, label=None):
        assert path == "ip/hotspot/profile/*7"
        self.patch_calls += 1
        self.profile["ssl-certificate"] = json["ssl-certificate"]
        raise requests.ConnectionError("connection reset by peer")


def test_ip_service_connection_reset_is_verified_as_success():
    client = RestartingServiceClient()

    update_ip_service(
        client,
        "www-ssl",
        "new_cert",
        reconnect_attempts=1,
        reconnect_delay=0,
    )

    assert client.patch_calls == 1
    assert client.service["certificate"] == "new_cert"


def test_ip_service_connection_reset_can_be_strict():
    client = RestartingServiceClient()

    with pytest.raises(requests.ConnectionError):
        update_ip_service(client, "www-ssl", "new_cert", verify_after_connection_error=False)


def test_hotspot_profile_connection_reset_is_verified_as_success():
    client = RestartingHotspotClient()

    update_hotspot_profile(client, "new_cert", "guest")

    assert client.patch_calls == 1
    assert client.profile["ssl-certificate"] == "new_cert"


def test_workflow_applies_api_ssl_after_other_bindings(monkeypatch, tmp_path):
    lineage = tmp_path
    (lineage / "privkey.pem").write_text("dummy", encoding="utf-8")
    (lineage / "fullchain.pem").write_text("dummy", encoding="utf-8")
    settings = load_settings(
        {
            "RENEWED_LINEAGE": str(lineage),
            "RENEWED_DOMAINS": "example.com",
            "MIKROTIK_DOMAIN": "example.com",
            "HOTSPOT_PROFILE_NAMES": "guest",
        }
    )
    calls = []

    import mikrotik_certbot.workflow as wf

    fake_client = SimpleNamespace(settings=settings)
    monkeypatch.setattr(wf, "RouterOSClient", lambda settings: fake_client)
    monkeypatch.setattr(wf, "detect_routeros_version", lambda client: ("7.17", True))
    monkeypatch.setattr(wf, "get_local_cert_serial", lambda path: None)
    monkeypatch.setattr(wf, "find_existing_certificate", lambda client, cert_name: None)
    monkeypatch.setattr(wf, "find_certificate_by_serial", lambda client, serial: None)
    monkeypatch.setattr(wf, "upload_certificate", lambda *args, **kwargs: calls.append("upload"))
    monkeypatch.setattr(wf, "confirm_file_exists", lambda *args, **kwargs: calls.append("file-confirm"))
    monkeypatch.setattr(wf, "remove_old_certificate", lambda *args, **kwargs: calls.append("remove-check"))
    monkeypatch.setattr(wf, "import_new_certificate", lambda *args, **kwargs: calls.append("import"))
    monkeypatch.setattr(wf, "confirm_certificate_present", lambda *args, **kwargs: calls.append("cert-confirm"))
    monkeypatch.setattr(wf, "delete_uploaded_file", lambda *args, **kwargs: True)
    monkeypatch.setattr(wf, "prune_old_certificates", lambda *args, **kwargs: calls.append("prune"))

    def record_service(client, service_name, cert_name, **kwargs):
        calls.append((service_name, kwargs))

    monkeypatch.setattr(wf, "update_ip_service", record_service)
    monkeypatch.setattr(
        wf,
        "update_hotspot_profile",
        lambda client, cert_name, profile: calls.append(("hotspot", profile)),
    )

    assert wf.run(settings) is True

    www_index = calls.index(("www-ssl", {}))
    hotspot_index = calls.index(("hotspot", "guest"))
    api_index = calls.index(("api-ssl", {}))
    prune_index = calls.index("prune")
    assert www_index < hotspot_index < api_index < prune_index
