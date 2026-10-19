import json
import subprocess

from app.docker_client import DockerClient


def test_inventory_uses_read_only_argv_and_sorts_running_first(monkeypatch):
    rows = [
        {"Names": "stopped", "Image": "alpine:3.22", "State": "exited", "ID": "123"},
        {"Names": "media", "Image": "media:latest", "State": "running", "ID": "456"},
    ]

    def run(command, **kwargs):
        assert command == ["docker", "container", "ls", "--all", "--format", "{{json .}}"]
        assert kwargs["timeout"] == 30
        assert "shell" not in kwargs
        return subprocess.CompletedProcess(
            command, 0, "\n".join(json.dumps(row) for row in rows), ""
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert DockerClient().available_containers() == [
        {"name": "media", "image": "media:latest", "state": "running", "id": "456"},
        {"name": "stopped", "image": "alpine:3.22", "state": "exited", "id": "123"},
    ]


def test_empty_inventory_is_valid(monkeypatch):
    monkeypatch.setattr(DockerClient, "_run", lambda *_args: "")
    assert DockerClient().available_containers() == []
