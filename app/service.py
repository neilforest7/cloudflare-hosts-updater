"""One task runner for startup, scheduled, and manual updates."""

import copy
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Config, ConfigStore, interval_seconds
from .docker_client import DockerClient
from .hosts import render_hosts
from .speedtest import SpeedTester
from .storage import atomic_write

logger = logging.getLogger("cloudflare-hosts-updater")


class BusyError(Exception):
    pass


class UpdaterService:
    def __init__(self, data_dir: Path, *, docker=None, tester=None, timezone="Asia/Shanghai"):
        self.data_dir = data_dir.resolve()
        data_dir = self.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self.store = ConfigStore(data_dir)
        self.docker = docker or DockerClient()
        self.tester = tester or SpeedTester(data_dir)
        self.timezone = ZoneInfo(timezone)
        self._task_lock = threading.Lock()
        self._condition = threading.Condition(threading.RLock())
        self._stopped = False
        self._scheduler = None
        self._job = None
        self._running = False
        self._history = self._read_history()
        if self._history and "status" in self._history[-1]:
            self._job = self._history[-1]
        self._next_run = None
        self._reset_next_run()

    def _timestamp(self):
        return datetime.now(self.timezone).isoformat(timespec="seconds")

    def _read_history(self):
        path = self.data_dir / "update_history.json"
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(history, list) or not all(isinstance(item, dict) for item in history):
                raise ValueError("历史记录格式错误")
            return history[-50:]
        except FileNotFoundError:
            return []
        except (ValueError, OSError):
            logger.exception("无法读取历史记录，保留损坏文件副本")
            if path.exists():
                atomic_write(
                    path.with_suffix(".json.corrupt"),
                    path.read_text(encoding="utf-8", errors="replace"),
                )
            return []

    def _reset_next_run(self):
        config = self.store.get()
        self._next_run = (
            time.time() + interval_seconds(config.update_interval)
            if config.update_enabled and config.cf_domains
            else None
        )

    def save_config(self, values: dict) -> Config:
        # A partial update starts from the current configuration, including empty values.
        with self._condition:
            config = Config.from_mapping(self.store.get().public() | values)
            self.store.save(config)
            self._reset_next_run()
            self._condition.notify_all()
            logger.info("配置已保存，下次任务使用新配置")
            return config

    def status(self):
        with self._condition:
            successes = [item for item in self._history if item.get("status") == "success"]
            return copy.deepcopy(
                {
                    "running": self._running,
                    "job": self._job,
                    "next_run": datetime.fromtimestamp(self._next_run, self.timezone).isoformat(
                        timespec="seconds"
                    )
                    if self._next_run
                    else None,
                    "last_success": successes[-1].get("timestamp") if successes else None,
                    "history": list(reversed(self._history)),
                    "configured": bool(self.store.get().cf_domains),
                }
            )

    def _prepare(self, mode: str, source: str):
        if mode not in ("speedtest", "cached"):
            raise ValueError("未知任务类型")
        if not self._task_lock.acquire(blocking=False):
            raise BusyError("已有任务正在运行，请等待完成")
        with self._condition:
            config = self.store.get()
            self._running = True
            self._job = {
                "id": uuid.uuid4().hex,
                "timestamp": self._timestamp(),
                "source": source,
                "is_scheduled": source == "scheduled",
                "mode": mode,
                "status": "running",
                "message": "正在准备更新" if mode == "cached" else "正在优选 IP",
                "ips": {},
                "containers": [],
            }
            return config, copy.deepcopy(self._job)

    def submit(self, mode="speedtest", source="manual"):
        config, job = self._prepare(mode, source)
        worker = threading.Thread(
            target=self._execute, args=(config, job), daemon=True, name="hosts-update"
        )
        try:
            worker.start()
        except Exception:
            with self._condition:
                self._running = False
                self._job = None
            self._task_lock.release()
            raise
        return job

    def run_update(self, mode="speedtest", source="manual"):
        """Synchronous entry point for scripts and integration tests."""
        config, job = self._prepare(mode, source)
        return self._execute(config, job)

    def _execute(self, config: Config, job: dict):
        started = time.monotonic()
        logger.info("开始任务 %s，来源 %s", job["id"], job["source"])
        try:
            if not config.cf_domains:
                raise ValueError("请先保存需要更新的域名")
            results = self.tester.get_results(config, cached=job["mode"] == "cached")
            template_path = self.data_dir / "template.hosts"
            template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
            content = render_hosts(results, config.cf_domains, template, self._timestamp())
            hosts_path = self.data_dir / "hosts"
            if hosts_path.exists():
                atomic_write(self.data_dir / "hosts.bak", hosts_path.read_text(encoding="utf-8"))
            atomic_write(hosts_path, content)
            job["ips"] = {domain: [item["ip"] for item in results] for domain in config.cf_domains}
            with self._condition:
                self._job["message"] = "正在更新目标容器"
            for name in config.target_containers:
                try:
                    changed = self.docker.update_hosts(name, content)
                    job["containers"].append({"name": name, "success": True, "changed": changed})
                except Exception as error:
                    logger.exception("容器 %s 更新失败", name)
                    job["containers"].append(
                        {"name": name, "success": False, "error": str(error)[:1000]}
                    )
                with self._condition:
                    self._job["containers"] = copy.deepcopy(job["containers"])
                    self._job["message"] = (
                        f"正在更新目标容器：{len(job['containers'])}/{len(config.target_containers)}"
                    )
            failures = sum(not item["success"] for item in job["containers"])
            total = len(job["containers"])
            job["status"] = (
                "partial" if 0 < failures < total else "failed" if failures else "success"
            )
            job["message"] = (
                f"容器更新完成：{total - failures}/{total} 成功"
                if total
                else "hosts 已生成；尚未配置目标容器"
            )
        except Exception as error:
            job["status"] = "failed"
            job["message"] = str(error)[:1000]
            logger.exception("任务 %s 失败", job["id"])
        finally:
            job["duration"] = round(time.monotonic() - started, 2)
            job["finished_at"] = self._timestamp()
            with self._condition:
                self._job = job
                self._history = [*self._history, job][-50:]
                try:
                    atomic_write(
                        self.data_dir / "update_history.json",
                        json.dumps(self._history, ensure_ascii=False, indent=2),
                    )
                except OSError:
                    logger.exception("历史记录保存失败")
                self._running = False
                self._task_lock.release()
                self._condition.notify_all()
            logger.info("任务 %s 结束：%s，%s", job["id"], job["status"], job["message"])
        return copy.deepcopy(job)

    def start(self):
        with self._condition:
            if self._scheduler is not None:
                return
            config = self.store.get()
            if config.update_enabled and config.cf_domains:
                try:
                    self.submit(source="startup")
                except BusyError:
                    logger.info("已有任务运行，跳过启动更新")
            self._scheduler = threading.Thread(
                target=self._schedule_loop, daemon=True, name="scheduler"
            )
            self._scheduler.start()

    def _schedule_loop(self):
        while True:
            with self._condition:
                if self._stopped:
                    return
                if self._next_run is None:
                    self._condition.wait()
                    continue
                delay = self._next_run - time.time()
                if delay > 0:
                    self._condition.wait(timeout=min(delay, 3600))
                    continue
                self._reset_next_run()
                # Hold the condition through submission: saving a disabled
                # schedule cannot race an already-due task.
                try:
                    self.submit(source="scheduled")
                except BusyError:
                    logger.info("已有任务运行，跳过本次定时更新")

    def stop(self):
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
