"""Bounded Docker CLI calls. User data is never inserted into shell programs."""

import json
import subprocess

from .hosts import merge_hosts

# Docker bind-mounts /etc/hosts: replace its contents rather than renaming it.
# stdin carries the content. The fixed script backs up, checks, and rolls back.
WRITE_HOSTS = """set -eu
new=$(mktemp)
trap 'rm -f "$new"' EXIT
cat > "$new"
cp /etc/hosts /etc/hosts.bak
if cat "$new" > /etc/hosts && cmp -s "$new" /etc/hosts; then
    exit 0
fi
cat /etc/hosts.bak > /etc/hosts
exit 1
"""


class DockerClient:
    def _run(self, *args, content=None):
        result = subprocess.run(
            ["docker", *args],
            input=content,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[:1000] or "Docker 命令失败")
        return result.stdout

    def read_hosts(self, name: str) -> str:
        return self._run("exec", name, "cat", "/etc/hosts")

    def update_hosts(self, name: str, content: str) -> bool:
        original = self.read_hosts(name)
        merged = merge_hosts(original, content)
        if merged == original:
            return False
        self._run("exec", "--user", "0", "-i", name, "sh", "-c", WRITE_HOSTS, content=merged)
        if self.read_hosts(name) != merged:
            raise RuntimeError("写入后校验失败，请检查容器状态和 /etc/hosts.bak")
        return True

    def status(self, name: str) -> dict:
        try:
            state = json.loads(
                self._run("container", "inspect", "--format", "{{json .State}}", name)
            )
            return {
                "name": name,
                "state": state["Status"],
                "hosts": self.read_hosts(name) if state["Running"] else "",
            }
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            return {"name": name, "state": "unavailable", "error": str(error)}
