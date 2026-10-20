import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import Config
from app.speedtest import SpeedTester, parse_results


def test_csv_bom_ipv6_and_bad_rows(tmp_path):
    path = tmp_path / "result.csv"
    path.write_text(
        '\ufeffIP 地址,平均延迟,其他\ninvalid,10,x\n1.1.1.1,nan,x\n1.1.1.1,4,x\n1.1.1.1,5,x\n2606:4700::1111,6,"a,b"\n8.8.8.8,-1,x\n'
    )
    assert parse_results(path, 2) == [
        {"ip": "1.1.1.1", "speed": "4"},
        {"ip": "2606:4700::1111", "speed": "6"},
    ]


@pytest.mark.parametrize("csv", ["", "wrong,header\n1.1.1.1,10\n", "IP 地址,平均延迟\ninvalid,1\n"])
def test_unusable_csv(tmp_path, csv):
    path = tmp_path / "result.csv"
    path.write_text(csv)
    with pytest.raises(ValueError):
        parse_results(path, 1)


def test_success_without_new_output_never_reuses_stale_csv(tmp_path, monkeypatch):
    tester = SpeedTester(tmp_path)
    tester.binary = shutil.which("true")
    tester.result_path.write_text("IP 地址,平均延迟\n1.1.1.1,10\n")
    previous = tester.result_path.read_bytes()
    with pytest.raises(ValueError, match="没有生成结果"):
        tester.get_results(Config())
    assert tester.result_path.read_bytes() == previous


def test_timeout_keeps_cache_and_cleans_temporary_directory(tmp_path, monkeypatch):
    tester = SpeedTester(tmp_path)
    tester.binary = shutil.which("true")
    tester.result_path.write_text("old cache")

    def timeout(command, **kwargs):
        assert kwargs["timeout"] == 2
        raise subprocess.TimeoutExpired(command, 2)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        tester.get_results(Config(speed_test_timeout=2))
    assert tester.result_path.read_text() == "old cache"
    assert not list(tmp_path.glob("speedtest-*"))


def test_success_publishes_only_valid_new_results(tmp_path, monkeypatch):
    tester = SpeedTester(tmp_path)
    tester.binary = shutil.which("true")

    def run(command, **kwargs):
        assert "shell" not in kwargs
        output = Path(command[command.index("-o") + 1])
        output.write_text("IP 地址,平均延迟\n8.8.8.8,20\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert tester.get_results(Config())[0]["ip"] == "8.8.8.8"
    assert tester.get_results(Config(), cached=True)[0]["ip"] == "8.8.8.8"


def test_preferred_ipv6_does_not_run_external_program(tmp_path):
    tester = SpeedTester(tmp_path)
    assert tester.get_results(Config(preferred_ip="2606:4700::1111")) == [
        {"ip": "2606:4700::1111", "speed": "0"}
    ]


def test_relative_data_and_binary_paths_work_from_binary_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    binary = tmp_path / "bin" / "fake-speedtest"
    binary.parent.mkdir()
    binary.write_text(
        '#!/bin/sh\nwhile [ "$#" -gt 0 ]; do\n'
        'if [ "$1" = "-o" ]; then shift; printf "IP 地址,平均延迟\\n1.1.1.1,10\\n" > "$1"; exit 0; fi\n'
        "shift\ndone\nexit 1\n"
    )
    binary.chmod(0o700)
    Path("data").mkdir()
    monkeypatch.setenv("CLOUDFLAREST_BIN", "bin/fake-speedtest")
    tester = SpeedTester(Path("data"))
    assert tester.get_results(Config()) == [{"ip": "1.1.1.1", "speed": "10"}]
