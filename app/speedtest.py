"""CloudflareSpeedTest execution and CSV validation."""

import csv
import math
import os
import shutil
import subprocess
import tempfile
from ipaddress import ip_address
from pathlib import Path

from .config import Config, speedtest_args


def parse_results(path: Path, count: int) -> list[dict]:
    results = []
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"IP 地址", "平均延迟"}.issubset(reader.fieldnames or []):
            raise ValueError("测速 CSV 缺少 IP 地址或平均延迟列")
        for row in reader:
            try:
                address = str(ip_address(row["IP 地址"].strip()))
                latency = float(row["平均延迟"])
                if not math.isfinite(latency) or latency < 0 or address in seen:
                    continue
            except (ValueError, TypeError, AttributeError):
                continue
            results.append({"ip": address, "speed": f"{latency:g}"})
            seen.add(address)
            if len(results) == count:
                break
    if not results:
        raise ValueError("测速未得到有效 IP，保留现有 hosts")
    return results


class SpeedTester:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.result_path = self.data_dir / "result.csv"
        binary = os.environ.get("CLOUDFLAREST_BIN", "/app/CloudflareST")
        self.binary = str(Path(shutil.which(binary) or binary).resolve())

    def get_results(self, config: Config, *, cached: bool = False) -> list[dict]:
        if config.preferred_ip:
            return [{"ip": config.preferred_ip, "speed": "0"}]
        if cached:
            if not self.result_path.exists():
                raise ValueError("暂无测速结果，请先运行优选或设置预设 IP")
            return parse_results(self.result_path, config.ip_count)
        # Every run gets a new output path, so a successful exit without results
        # can never silently reuse an older CSV.
        with tempfile.TemporaryDirectory(prefix="speedtest-", dir=self.data_dir) as temporary:
            result_path = Path(temporary) / "result.csv"
            command = [self.binary, *speedtest_args(config.speed_test_args), "-o", str(result_path)]
            result = subprocess.run(
                command,
                cwd=Path(self.binary).resolve().parent,
                capture_output=True,
                text=True,
                timeout=config.speed_test_timeout,
            )
            if result.returncode:
                raise RuntimeError(
                    f"测速失败：{result.stderr.strip()[:1000] or result.stdout.strip()[-1000:]}"
                )
            if not result_path.exists():
                raise ValueError("测速完成但没有生成结果，保留现有 hosts")
            results = parse_results(result_path, config.ip_count)
            os.replace(result_path, self.result_path)
            return results
