from types import SimpleNamespace

import pytest
import requests

from mikrotik_certbot.config import load_settings
from mikrotik_certbot.routeros import (
    restart_www_ssl_via_ssh,
    update_hotspot_profile,
    update_ip_service,
    update_www_ssl_via_ssh,
    wait_for_rest_api,
)


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


class FlakyRestClient:
    def __init__(self):
        self.calls = 0

    def get(self, path, params=None, timeout=10, label=None):
        assert path == "system/resource"
        self.calls += 1
        if self.calls == 1:
            raise requests.ConnectionError("rest is restarting")
        return SimpleNamespace(ok=True)


class FailedRestClient:
    def __init__(self):
        self.calls = 0

    def get(self, path, params=None, timeout=10, label=None):
        assert path == "system/resource"
        self.calls += 1
        if self.calls == 2:
            raise requests.ConnectionError("rest is restarting")
        return SimpleNamespace(ok=False)


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


def test_wait_for_rest_api_sleeps_then_probes_until_ready(monkeypatch):
    client = FlakyRestClient()
    sleeps = []

    import mikrotik_certbot.routeros as routeros

    monkeypatch.setattr(routeros.time, "sleep", lambda seconds: sleeps.append(seconds))

    wait_for_rest_api(client, initial_delay=5, attempts=2, delay=1)

    assert sleeps == [5, 1]
    assert client.calls == 2


def test_wait_for_rest_api_sleeps_after_every_failed_probe(monkeypatch):
    client = FailedRestClient()
    sleeps = []

    import mikrotik_certbot.routeros as routeros

    monkeypatch.setattr(routeros.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(RuntimeError, match="did not become ready"):
        wait_for_rest_api(client, initial_delay=5, attempts=3, delay=1)

    assert sleeps == [5, 1, 1]
    assert client.calls == 3


def test_restart_www_ssl_via_ssh_runs_toggle_and_closes(monkeypatch):
    calls = []

    class Channel:
        def recv_exit_status(self):
            return 0

    class Stream:
        channel = Channel()

        def read(self):
            return b""

    class SSH:
        def exec_command(self, command, timeout):
            calls.append((command, timeout))
            return None, Stream(), Stream()

        def close(self):
            calls.append("close")

    import mikrotik_certbot.routeros as routeros

    monkeypatch.setattr(routeros, "_connect_ssh", lambda client: SSH())
    restart_www_ssl_via_ssh(SimpleNamespace())

    assert calls == [
        ('/ip service disable [find name="www-ssl"]; /ip service enable [find name="www-ssl"]', 20),
        "close",
    ]


@pytest.mark.parametrize(
    ("exit_status", "output", "error", "fails"),
    [
        (0, b"MIKROTIK_CERTBOT_WWW_SSL_UPDATED\r\n", b"", False),
        (1, b"", b"permission denied", True),
        (0, b"", b"script failed", True),
        (0, b"", b"", True),
    ],
)
def test_update_www_ssl_via_ssh_sequence_and_errors(monkeypatch, exit_status, output, error, fails):
    calls = []

    class Channel:
        def recv_exit_status(self):
            return exit_status

    class Stream:
        channel = Channel()

        def __init__(self, content):
            self.content = content

        def read(self):
            return self.content

    class SSH:
        def exec_command(self, command, timeout):
            calls.append(command)
            assert timeout == 20
            return None, Stream(output), Stream(error)

        def close(self):
            calls.append("close")

    import mikrotik_certbot.routeros as routeros

    monkeypatch.setattr(routeros, "_connect_ssh", lambda client: SSH())
    if fails:
        with pytest.raises(RuntimeError, match="SSH www-ssl update failed"):
            update_www_ssl_via_ssh(SimpleNamespace(), 'new_"cert$\\')
    else:
        update_www_ssl_via_ssh(SimpleNamespace(), 'new_"cert$\\')

    command = calls[0]
    assert command.index("disable $service") < command.index("set $service certificate=")
    assert command.index("set $service certificate=") < command.index(":delay 2s")
    assert command.index(":delay 2s") < command.index("enable $service")
    assert 'certificate="new_\\"cert\\$\\\\"' in command
    assert '} on-error={ /ip service enable $service;' in command
    assert command.count("enable $service") == 2
    assert "get $service certificate" in command
    assert calls[-1] == "close"


@pytest.mark.parametrize("cert_name", ["", "new\ncert", "new\rcert", "new\x00cert"])
def test_update_www_ssl_rejects_invalid_names_before_ssh(monkeypatch, cert_name):
    import mikrotik_certbot.routeros as routeros

    def unexpected_ssh(client):
        pytest.fail("Invalid names must be rejected before connecting")

    monkeypatch.setattr(routeros, "_connect_ssh", unexpected_ssh)
    with pytest.raises(ValueError, match="Certificate name"):
        update_www_ssl_via_ssh(SimpleNamespace(), cert_name)


def test_rebind_www_ssl_via_ssh_cycles_previous_to_new_certificate(monkeypatch):
    calls = []

    class Channel:
        def recv_exit_status(self):
            return 0

    class Stream:
        channel = Channel()

        def __init__(self, content):
            self.content = content

        def read(self):
            return self.content

    class SSH:
        def exec_command(self, command, timeout):
            calls.append((command, timeout))
            return None, Stream(b"MIKROTIK_CERTBOT_WWW_SSL_REBOUND\r\n"), Stream(b"")

        def close(self):
            calls.append("close")

    import mikrotik_certbot.routeros as routeros

    monkeypatch.setattr(routeros, "_connect_ssh", lambda client: SSH())
    routeros.rebind_www_ssl_via_ssh(SimpleNamespace(), "old_cert", "new_cert")

    command = calls[0][0]
    old_binding = 'set $service certificate="old_cert"'
    new_binding = 'set $service certificate="new_cert"'
    assert command.index("disable $service") < command.index(old_binding)
    assert command.index(old_binding) < command.index(":delay 2s")
    assert command.index(":delay 2s") < command.index(new_binding)
    assert command.index(new_binding) < command.rindex("enable $service")
    assert '} on-error={ /ip service enable $service;' in command
    assert calls[-1] == "close"


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
    monkeypatch.setattr(wf, "get_ip_service_certificate", lambda *args: None)
    monkeypatch.setattr(wf, "upload_certificate", lambda *args, **kwargs: calls.append("upload"))
    monkeypatch.setattr(wf, "confirm_file_exists", lambda *args, **kwargs: calls.append("file-confirm"))
    monkeypatch.setattr(wf, "remove_old_certificate", lambda *args, **kwargs: calls.append("remove-check"))
    monkeypatch.setattr(wf, "import_new_certificate", lambda *args, **kwargs: calls.append("import"))
    monkeypatch.setattr(wf, "confirm_certificate_present", lambda *args, **kwargs: calls.append("cert-confirm"))
    monkeypatch.setattr(wf, "delete_uploaded_file", lambda *args, **kwargs: True)
    monkeypatch.setattr(wf, "prune_old_certificates", lambda *args, **kwargs: calls.append("prune"))
    monkeypatch.setattr(wf, "wait_for_rest_api", lambda *args, **kwargs: calls.append(("rest-wait", kwargs)))

    def record_service(client, service_name, cert_name, **kwargs):
        calls.append((service_name, kwargs))

    monkeypatch.setattr(wf, "update_ip_service", record_service)
    monkeypatch.setattr(
        wf, "update_www_ssl_via_ssh", lambda client, cert_name: record_service(client, "www-ssl", cert_name)
    )
    monkeypatch.setattr(
        wf,
        "update_hotspot_profile",
        lambda client, cert_name, profile: calls.append(("hotspot", profile)),
    )

    assert wf.run(settings) is True

    www_index = calls.index(("www-ssl", {}))
    rest_wait_index = calls.index(("rest-wait", {"initial_delay": 5}))
    hotspot_index = calls.index(("hotspot", "guest"))
    api_index = calls.index(("api-ssl", {}))
    prune_index = calls.index("prune")
    assert www_index < rest_wait_index < hotspot_index < api_index < prune_index


def test_workflow_recovers_www_ssl_once_before_remaining_rest_updates(monkeypatch, tmp_path):
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
    monkeypatch.setattr(wf, "get_ip_service_certificate", lambda *args: "old_cert")
    monkeypatch.setattr(wf, "upload_certificate", lambda *args, **kwargs: None)
    monkeypatch.setattr(wf, "confirm_file_exists", lambda *args, **kwargs: None)
    monkeypatch.setattr(wf, "remove_old_certificate", lambda *args, **kwargs: None)
    monkeypatch.setattr(wf, "import_new_certificate", lambda *args, **kwargs: None)
    monkeypatch.setattr(wf, "confirm_certificate_present", lambda *args, **kwargs: None)
    monkeypatch.setattr(wf, "delete_uploaded_file", lambda *args, **kwargs: True)
    monkeypatch.setattr(wf, "prune_old_certificates", lambda *args, **kwargs: calls.append("prune"))
    monkeypatch.setattr(wf, "update_ip_service", lambda *args, **kwargs: calls.append(args[1]))
    monkeypatch.setattr(wf, "update_www_ssl_via_ssh", lambda *args: calls.append("www-ssl"))
    monkeypatch.setattr(wf, "rebind_www_ssl_via_ssh", lambda *args: calls.append("ssh-rebind"))
    monkeypatch.setattr(wf, "update_hotspot_profile", lambda *args, **kwargs: calls.append("hotspot"))

    waits = iter([RuntimeError("initial REST failure"), None])

    def wait(client, **kwargs):
        calls.append(("wait", kwargs))
        outcome = next(waits)
        if outcome:
            raise outcome

    monkeypatch.setattr(wf, "wait_for_rest_api", wait)

    assert wf.run(settings) is True
    assert calls == [
        "www-ssl",
        ("wait", {"initial_delay": 5}),
        "ssh-rebind",
        ("wait", {"initial_delay": 0}),
        "hotspot",
        "api-ssl",
        "prune",
    ]


@pytest.mark.parametrize("failure_stage", ["update", "restart"])
def test_workflow_stops_before_other_updates_when_ssh_fails(monkeypatch, tmp_path, failure_stage):
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
    monkeypatch.setattr(wf, "get_ip_service_certificate", lambda *args: None)
    monkeypatch.setattr(wf, "upload_certificate", lambda *args, **kwargs: None)
    monkeypatch.setattr(wf, "confirm_file_exists", lambda *args, **kwargs: None)
    monkeypatch.setattr(wf, "remove_old_certificate", lambda *args, **kwargs: None)
    monkeypatch.setattr(wf, "import_new_certificate", lambda *args, **kwargs: None)
    monkeypatch.setattr(wf, "confirm_certificate_present", lambda *args, **kwargs: None)
    monkeypatch.setattr(wf, "delete_uploaded_file", lambda *args, **kwargs: True)
    monkeypatch.setattr(wf, "prune_old_certificates", lambda *args, **kwargs: calls.append("prune"))
    monkeypatch.setattr(wf, "update_ip_service", lambda *args, **kwargs: calls.append(args[1]))
    def update_www_ssl(client, cert_name):
        calls.append("www-ssl")
        if failure_stage == "update":
            raise RuntimeError("SSH update failed")

    monkeypatch.setattr(wf, "update_www_ssl_via_ssh", update_www_ssl)
    monkeypatch.setattr(wf, "update_hotspot_profile", lambda *args, **kwargs: calls.append("hotspot"))
    monkeypatch.setattr(
        wf,
        "wait_for_rest_api",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("REST failed")),
    )
    monkeypatch.setattr(
        wf,
        "restart_www_ssl_via_ssh",
        lambda client: (_ for _ in ()).throw(RuntimeError("SSH failed")),
    )

    with pytest.raises(RuntimeError, match="SSH (update|recovery) failed"):
        wf.run(settings)

    assert calls == ["www-ssl"]
