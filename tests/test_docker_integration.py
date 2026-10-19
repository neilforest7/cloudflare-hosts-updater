"""Opt-in test against disposable containers on the local Docker daemon."""

import os
import subprocess
import uuid

import pytest

from app.docker_client import DockerClient
from app.hosts import END, render_hosts
from app.service import UpdaterService

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_TESTS") != "1",
    reason="Set RUN_DOCKER_TESTS=1 to create disposable local containers",
)


def test_real_container_migration_idempotence_and_failure_reporting(tmp_path, monkeypatch):
    for key in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    name = "cfhu-test-" + uuid.uuid4().hex[:12]
    command = ["docker", "--host=unix:///var/run/docker.sock"]
    subprocess.run(
        [*command, "run", "-d", "--name", name, "--network", "none", "alpine:3.22", "sleep", "300"],
        check=True,
        capture_output=True,
        timeout=120,
    )
    try:
        client = DockerClient()
        original = client.read_hosts(name)
        legacy = render_hosts([{"ip": "8.8.8.8", "speed": "5"}], ("old.test",), "", "old")
        seeded = legacy + original + "10.20.30.40 preserve.test\n"
        subprocess.run(
            [*command, "exec", "-i", name, "sh", "-c", "cat > /etc/hosts"],
            input=seeded,
            text=True,
            check=True,
            timeout=30,
        )
        service = UpdaterService(tmp_path)
        (tmp_path / "template.hosts").write_text(
            "{ip} {domain} # literal '$(touch /tmp/cfhu-injected)'\n"
        )
        service.save_config(
            {
                "CF_DOMAINS": "example.com",
                "PREFERRED_IP": "1.1.1.1",
                "TARGET_CONTAINERS": f"{name},{name}-missing",
            }
        )
        job = service.run_update()
        assert job["status"] == "partial"
        updated = client.read_hosts(name)
        assert original in updated
        assert "10.20.30.40 preserve.test\n" in updated
        assert "8.8.8.8 old.test" not in updated
        assert updated.count(END) == 1
        client._run("exec", name, "test", "!", "-e", "/tmp/cfhu-injected")
        assert client.update_hosts(name, (tmp_path / "hosts").read_text()) is False
        assert client._run("exec", name, "cat", "/etc/hosts.bak") == seeded
        service.save_config({"TARGET_CONTAINERS": name, "PREFERRED_IP": "2606:4700::1111"})
        assert service.run_update()["status"] == "success"
        assert "2606:4700::1111 example.com" in client.read_hosts(name)
    finally:
        subprocess.run([*command, "rm", "-f", name], check=True, capture_output=True, timeout=30)
