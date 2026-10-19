"""Validated configuration, including the original [general] TOML format."""

import os
import re
import shlex
import threading
from dataclasses import asdict, dataclass
from ipaddress import ip_address
from pathlib import Path

import toml

from .storage import atomic_write


def interval_seconds(value: str) -> int:
    match = re.fullmatch(r"([0-9]{1,8})([smhd]?)", str(value).strip().lower())
    if not match or int(match[1]) == 0:
        raise ValueError("更新间隔应为正整数加 s/m/h/d，例如 30m、12h；纯数字按小时计算")
    seconds = int(match[1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400, "": 3600}[match[2]]
    if seconds > 365 * 86400:
        raise ValueError("更新间隔不能超过 365 天")
    return seconds


def split_list(value) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        value = ",".join(str(item) for item in value)
    return tuple(dict.fromkeys(item for item in re.split(r"[\s,]+", str(value).strip()) if item))


def speedtest_args(value: str) -> list[str]:
    try:
        args = shlex.split(value)
    except ValueError as error:
        raise ValueError("测速参数中的引号不匹配") from error
    if any(re.fullmatch(r"--?o(?:=.*)?", arg) for arg in args):
        raise ValueError("测速结果路径由程序管理，请移除 -o 参数")
    return args


@dataclass(frozen=True)
class Config:
    update_interval: str = "12h"
    target_containers: tuple[str, ...] = ()
    cf_domains: tuple[str, ...] = ()
    ip_count: int = 1
    preferred_ip: str = ""
    speed_test_args: str = ""
    speed_test_timeout: int = 1800
    update_enabled: bool = True

    @classmethod
    def from_mapping(cls, values: dict):
        fields = cls.__dataclass_fields__
        values = {key.lower(): value for key, value in values.items() if key.lower() in fields}
        data = asdict(cls()) | values
        data["update_interval"] = str(data["update_interval"]).strip().lower()
        interval_seconds(data["update_interval"])
        for key, limit in (("ip_count", 20), ("speed_test_timeout", 86400)):
            try:
                if isinstance(data[key], bool) or not re.fullmatch(r"[0-9]+", str(data[key])):
                    raise ValueError
                data[key] = int(data[key])
                if not 1 <= data[key] <= limit:
                    raise ValueError
            except (TypeError, ValueError) as error:
                label = "IP 数量" if key == "ip_count" else "测速超时秒数"
                raise ValueError(f"{label}应为 1–{limit} 的整数") from error
        data["target_containers"] = split_list(data["target_containers"])
        for name in data["target_containers"]:
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", name):
                raise ValueError(f"无效的容器名称：{name}")
        domains = []
        for value in split_list(data["cf_domains"]):
            try:
                domain = value.rstrip(".").encode("idna").decode("ascii").lower()
                if len(domain) > 253 or not all(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
                    for part in domain.split(".")
                ):
                    raise ValueError
                # An IP literal is not a hosts alias.
                try:
                    ip_address(domain)
                except ValueError:
                    pass
                else:
                    raise ValueError
            except (UnicodeError, ValueError) as error:
                raise ValueError(f"无效的域名：{value}；请只填写域名，不含协议或路径") from error
            domains.append(domain)
        data["cf_domains"] = tuple(dict.fromkeys(domains))
        data["preferred_ip"] = str(data["preferred_ip"]).strip()
        if data["preferred_ip"]:
            try:
                if "%" in data["preferred_ip"]:
                    raise ValueError
                data["preferred_ip"] = str(ip_address(data["preferred_ip"]))
            except ValueError as error:
                raise ValueError("预设 IP 必须是有效的 IPv4 或 IPv6 地址") from error
        data["speed_test_args"] = str(data["speed_test_args"]).strip()
        speedtest_args(data["speed_test_args"])
        enabled = data["update_enabled"]
        if isinstance(enabled, str) and enabled.lower() in ("true", "false", "1", "0"):
            enabled = enabled.lower() in ("true", "1")
        if not isinstance(enabled, bool):
            raise ValueError("自动更新开关应为 true 或 false")
        data["update_enabled"] = enabled
        return cls(**data)

    def public(self) -> dict:
        data = asdict(self)
        data["target_containers"] = ",".join(self.target_containers)
        data["cf_domains"] = ",".join(self.cf_domains)
        return {key.upper(): value for key, value in data.items()}


class ConfigStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "config.toml"
        self.lock = threading.RLock()
        if self.path.exists() and self.path.stat().st_size:
            # Saved empty values are intentional; never restore the old defaults.
            self.current = Config.from_mapping(toml.load(self.path).get("general", {}))
        else:
            self.current = Config.from_mapping(
                {key: os.environ[key] for key in Config().public() if key in os.environ}
            )
            self.save(self.current)

    def get(self) -> Config:
        with self.lock:
            return self.current

    def save(self, config: Config) -> None:
        with self.lock:
            values = {key.lower(): value for key, value in config.public().items()}
            atomic_write(self.path, toml.dumps({"general": values}))
            self.current = config
