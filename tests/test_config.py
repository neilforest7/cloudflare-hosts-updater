import pytest
import toml

from app.config import Config, ConfigStore, interval_seconds, speedtest_args


@pytest.mark.parametrize(
    ("value", "seconds"), [("12h", 43200), ("30m", 1800), ("1d", 86400), ("2", 7200), ("1s", 1)]
)
def test_intervals(value, seconds):
    assert interval_seconds(value) == seconds


@pytest.mark.parametrize(
    "values",
    [
        {"UPDATE_INTERVAL": "0h"},
        {"UPDATE_INTERVAL": "99999999d"},
        {"UPDATE_INTERVAL": "bad"},
        {"IP_COUNT": 0},
        {"IP_COUNT": "1.5"},
        {"IP_COUNT": True},
        {"PREFERRED_IP": "999.1.1.1"},
        {"PREFERRED_IP": "fe80::1%eth0"},
        {"TARGET_CONTAINERS": "app;touch /tmp/pwned"},
        {"TARGET_CONTAINERS": "--help"},
        {"CF_DOMAINS": "https://example.com/a"},
        {"CF_DOMAINS": "*.example.com"},
        {"CF_DOMAINS": "1.1.1.1"},
        {"SPEED_TEST_ARGS": "-o /etc/hosts"},
        {"SPEED_TEST_ARGS": "--o=elsewhere"},
        {"SPEED_TEST_ARGS": '-url "oops'},
        {"SPEED_TEST_TIMEOUT": 0},
        {"UPDATE_ENABLED": "maybe"},
    ],
)
def test_invalid_config(values):
    with pytest.raises(ValueError):
        Config.from_mapping(values)


def test_normalization_and_quoted_args():
    config = Config.from_mapping(
        {
            "CF_DOMAINS": "Example.com,example.com\r\n例子.中国",
            "TARGET_CONTAINERS": ["app", "app", "other"],
            "PREFERRED_IP": "2606:4700::1111",
        }
    )
    assert config.cf_domains == ("example.com", "xn--fsqu00a.xn--fiqs8s")
    assert config.target_containers == ("app", "other")
    assert speedtest_args('-url "https://example.com/file?a=1&b=2"') == [
        "-url",
        "https://example.com/file?a=1&b=2",
    ]


def test_legacy_config_and_intentional_empty_values(tmp_path, monkeypatch):
    values = {
        "general": {
            "target_containers": "",
            "cf_domains": "example.com\nother.com",
            "preferred_ip": "",
            "ip_count": 2,
        }
    }
    (tmp_path / "config.toml").write_text(toml.dumps(values))
    monkeypatch.setenv("PREFERRED_IP", "1.1.1.1")
    store = ConfigStore(tmp_path)
    assert store.get().preferred_ip == ""
    assert store.get().target_containers == ()
    assert store.get().cf_domains == ("example.com", "other.com")
    store.save(Config.from_mapping({"CF_DOMAINS": ""}))
    assert ConfigStore(tmp_path).get().cf_domains == ()


def test_first_run_environment_only_initializes_once(tmp_path, monkeypatch):
    monkeypatch.setenv("PREFERRED_IP", "1.1.1.1")
    assert ConfigStore(tmp_path).get().preferred_ip == "1.1.1.1"
    monkeypatch.setenv("PREFERRED_IP", "8.8.8.8")
    assert ConfigStore(tmp_path).get().preferred_ip == "1.1.1.1"


def test_failed_save_keeps_memory_and_file(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path)
    before = store.path.read_bytes()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("app.config.atomic_write", fail)
    with pytest.raises(OSError):
        store.save(Config(preferred_ip="1.1.1.1"))
    assert store.get().preferred_ip == ""
    assert store.path.read_bytes() == before
