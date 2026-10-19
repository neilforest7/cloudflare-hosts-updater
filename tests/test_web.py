import base64
import re
import threading

import pytest

from app.service import UpdaterService
from app.web import create_app
from tests.test_service import FakeDocker


@pytest.fixture
def web(tmp_path):
    service = UpdaterService(tmp_path, docker=FakeDocker())
    app = create_app(service, password="")
    app.config["TESTING"] = True
    client = app.test_client()
    page = client.get("/")
    token = re.search(r'name="csrf-token" content="([^"]+)"', page.text)[1]
    return service, client, {"X-CSRFToken": token}


def test_config_validation_and_no_implicit_container_writes(web):
    service, client, headers = web
    result = client.post(
        "/api/config",
        headers=headers,
        json={"PREFERRED_IP": "1.1.1.1", "CF_DOMAINS": "example.com", "TARGET_CONTAINERS": "app"},
    )
    assert result.status_code == 200
    assert not service.docker.writes
    assert (
        client.post("/api/config", headers=headers, json={"PREFERRED_IP": "bad"}).status_code == 400
    )
    assert service.store.get().preferred_ip == "1.1.1.1"
    assert client.post("/api/config", headers=headers, json=[]).status_code == 400


def test_csrf_and_security_headers(web):
    _, client, _ = web
    assert client.post("/update_hosts").status_code == 403
    assert client.post("/api/config", json={}).status_code == 403
    assert client.post("/api/config", json={}, headers={"X-CSRFToken": "无效"}).status_code == 403
    response = client.get("/")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]


def test_async_jobs_remain_observable_and_overlap_returns_conflict(web):
    service, client, headers = web
    entered, release = threading.Event(), threading.Event()

    class BlockingTester:
        def get_results(self, config, **kwargs):
            entered.set()
            assert release.wait(timeout=3)
            return [{"ip": "1.1.1.1", "speed": "0"}]

    service.tester = BlockingTester()
    service.save_config({"CF_DOMAINS": "example.com"})
    response = client.post("/run_speedtest", headers=headers)
    assert response.status_code == 202
    assert entered.wait(timeout=1)
    try:
        assert client.get("/api/status").json["running"]
        assert client.post("/update_hosts", headers=headers).status_code == 409
        assert client.get("/healthz").status_code == 200
    finally:
        release.set()
    with service._condition:
        assert service._condition.wait_for(lambda: not service._running, timeout=3)


def test_authentication_protects_reads_and_writes(tmp_path):
    app = create_app(UpdaterService(tmp_path), username="owner", password="secret")
    client = app.test_client()
    for path in ("/", "/api/config", "/api/logs", "/api/status", "/api/hosts"):
        assert client.get(path).status_code == 401
    assert client.get("/healthz").status_code == 200
    auth = "Basic " + base64.b64encode(b"owner:secret").decode()
    assert client.get("/", headers={"Authorization": auth}).status_code == 200


def test_logs_limits_and_multi_ip_artifact(web):
    service, client, _ = web
    (service.data_dir / "updater.log").write_text("\n".join(str(i) for i in range(1200)))
    assert len(client.get("/api/logs?lines=999999").json["logs"].splitlines()) == 1000
    assert len(client.get("/api/logs?lines=-1").json["logs"].splitlines()) == 1
    assert client.get("/api/logs?lines=invalid").status_code == 200
