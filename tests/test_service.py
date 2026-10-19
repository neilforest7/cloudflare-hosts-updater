import json
import threading
import time

import pytest

from app.service import BusyError, UpdaterService


class FakeDocker:
    def __init__(self):
        self.writes = {}

    def update_hosts(self, name, content):
        if name == "missing":
            raise RuntimeError("container does not exist")
        self.writes[name] = content
        return True

    def status(self, name):
        return {"name": name, "state": "running", "hosts": self.writes.get(name, "")}


def configured_service(tmp_path, **kwargs):
    service = UpdaterService(tmp_path, docker=FakeDocker(), **kwargs)
    service.save_config(
        {"CF_DOMAINS": "example.com", "TARGET_CONTAINERS": "app", "PREFERRED_IP": "1.1.1.1"}
    )
    return service


@pytest.mark.parametrize(
    ("targets", "expected"),
    [("app", "success"), ("app,missing", "partial"), ("missing", "failed"), ("", "success")],
)
def test_actual_container_outcomes_are_recorded(tmp_path, targets, expected):
    service = configured_service(tmp_path)
    service.save_config({"TARGET_CONTAINERS": targets})
    result = service.run_update()
    assert result["status"] == expected
    history = json.loads((tmp_path / "update_history.json").read_text())
    assert history[-1]["status"] == expected
    assert service.status()["running"] is False
    assert result["ips"] == {"example.com": ["1.1.1.1"]}
    assert bool(service.status()["last_success"]) == (expected == "success")


def test_failures_keep_existing_hosts_and_allow_retry(tmp_path):
    service = configured_service(tmp_path)
    service.run_update()
    before = (tmp_path / "hosts").read_bytes()
    service.save_config({"PREFERRED_IP": ""})
    assert service.run_update("cached")["status"] == "failed"
    assert (tmp_path / "hosts").read_bytes() == before
    service.save_config({"PREFERRED_IP": "8.8.8.8"})
    assert service.run_update()["status"] == "success"
    assert "8.8.8.8" in service.docker.writes["app"]


def test_one_task_and_configuration_snapshot(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class BlockingTester:
        def get_results(self, config, **kwargs):
            entered.set()
            assert release.wait(timeout=3)
            return [{"ip": config.preferred_ip, "speed": "0"}]

    service = configured_service(tmp_path, tester=BlockingTester())
    service.submit()
    assert entered.wait(timeout=1)
    try:
        service.start()  # An existing manual task must not make startup fail.
        with pytest.raises(BusyError):
            service.submit()
        service.save_config({"CF_DOMAINS": "new.test", "PREFERRED_IP": "8.8.8.8"})
        assert service.status()["running"]
    finally:
        release.set()
        service.stop()
    with service._condition:
        assert service._condition.wait_for(lambda: not service._running, timeout=3)
    assert "1.1.1.1 example.com" in service.docker.writes["app"]
    assert "new.test" not in service.docker.writes["app"]
    service.run_update()
    assert "8.8.8.8 new.test" in service.docker.writes["app"]


def test_schedule_save_and_disable(tmp_path):
    service = configured_service(tmp_path)
    service.save_config({"UPDATE_INTERVAL": "30m"})
    assert abs(service._next_run - time.time() - 1800) < 2
    service.save_config({"UPDATE_ENABLED": False})
    assert service.status()["next_run"] is None
    service.start()
    try:
        service.save_config({"UPDATE_ENABLED": True})
        with service._condition:
            service._next_run = time.time() - 1
            service._condition.notify_all()
            assert service._condition.wait_for(lambda: bool(service._history), timeout=3)
        assert service.status()["history"][0]["source"] == "scheduled"
    finally:
        service.stop()


def test_legacy_history_and_bounded_storage(tmp_path):
    legacy = {
        "timestamp": "2025-03-25 12:00:00",
        "is_scheduled": False,
        "ips": {"example.com": "1.1.1.1"},
    }
    (tmp_path / "update_history.json").write_text(json.dumps([legacy] * 50))
    service = configured_service(tmp_path)
    assert service.status()["last_success"] is None
    service.run_update()
    assert len(service.status()["history"]) == 50
    assert UpdaterService(tmp_path).status()["job"]["status"] == "success"


def test_corrupt_history_is_preserved(tmp_path):
    (tmp_path / "update_history.json").write_text("[broken")
    service = UpdaterService(tmp_path)
    assert service.status()["history"] == []
    assert (tmp_path / "update_history.json.corrupt").read_text() == "[broken"
