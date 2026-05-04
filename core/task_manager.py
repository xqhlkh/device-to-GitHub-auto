"""
任务管理模块 —— 负责任务的增删改查、启停调度、配置持久化。
每个运行中的任务拥有独立的 watchdog 监控 + 防抖定时器 + Git 同步线程。
"""

import os
import json
import uuid
import logging
import threading
from datetime import datetime
from typing import Callable

from core.monitor import FolderMonitor
from core.git_handler import do_sync

logger = logging.getLogger("TaskManager")

# 防抖等待秒数（文件变化停止后等待此时间再同步）
DEBOUNCE_SECONDS = 3.0

# 每个任务最多保留的日志条数
MAX_LOG_ENTRIES = 100


def _get_config_path() -> str:
    """返回 config.json 的绝对路径（与 main.py 同目录）。"""
    import sys
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        # 向上两级：core/task_manager.py → github_sync_monitor/
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "config.json")


class TaskWorker:
    """
    单个同步任务的工作线程控制器。
    持有 FolderMonitor（watchdog）和防抖定时器。
    """

    def __init__(self, task_config: dict, on_status_change: Callable,
                 on_log: Callable, on_sync_done: Callable):
        self.config = task_config
        self._on_status_change = on_status_change   # (task_id, status) -> None
        self._on_log = on_log                       # (task_id, message) -> None
        self._on_sync_done = on_sync_done           # (task_id, timestamp) -> None

        self._monitor: FolderMonitor | None = None
        self._debounce_timer: threading.Timer | None = None
        self._sync_lock = threading.Lock()          # 防止并发同步
        self._stopped = threading.Event()

    # ── 公共接口 ──────────────────────────────────────────

    def start(self):
        """启动监控。"""
        self._stopped.clear()
        try:
            self._monitor = FolderMonitor(
                folder_path=self.config["local_path"],
                on_change=self._on_file_change,
            )
            self._monitor.start()
            self._on_status_change(self.config["id"], "running")
            self._add_log("监控已启动")
        except Exception as e:
            self._on_status_change(self.config["id"], "error")
            self._add_log(f"启动失败: {e}")

    def stop(self):
        """停止监控。"""
        self._stopped.set()
        # 取消防抖定时器
        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer = None
        # 停止 watchdog
        if self._monitor:
            self._monitor.stop()
            self._monitor = None
        self._add_log("监控已停止")
        self._on_status_change(self.config["id"], "stopped")

    # ── 内部方法 ──────────────────────────────────────────

    def _add_log(self, message: str):
        """添加日志条目（自动加时间戳），限制条数。"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        logs = self.config.get("logs", [])
        logs.append(entry)
        if len(logs) > MAX_LOG_ENTRIES:
            logs = logs[-MAX_LOG_ENTRIES:]
        self.config["logs"] = logs
        self._on_log(self.config["id"], entry)

    def _on_file_change(self):
        """watchdog 检测到文件变化 → 重置防抖定时器。"""
        if self._stopped.is_set():
            return
        if self._debounce_timer:
            self._debounce_timer.cancel()
        self._debounce_timer = threading.Timer(DEBOUNCE_SECONDS, self._do_sync)
        self._debounce_timer.daemon = True
        self._debounce_timer.start()

    def _do_sync(self):
        """防抖定时器触发 → 在后台线程中执行 Git 同步。"""
        if self._stopped.is_set():
            return
        # 防止并发同步
        if not self._sync_lock.acquire(blocking=False):
            self._add_log("上一次同步仍在进行，跳过")
            return

        thread = threading.Thread(target=self._run_sync, daemon=True)
        thread.start()

    def _run_sync(self):
        """实际执行 Git 同步（在后台线程中调用）。"""
        try:
            self._add_log("检测到文件变更，开始同步...")
            result = do_sync(
                local_path=self.config["local_path"],
                remote_url=self.config["remote_url"],
                branch=self.config["branch"],
                commit_message=self.config["commit_message"],
            )
            if result.success:
                now = datetime.now()
                self.config["last_sync"] = now.strftime("%Y-%m-%d %H:%M:%S")
                self._on_sync_done(self.config["id"], self.config["last_sync"])
                self._add_log(f"同步成功: {result.message}")
                # 如果之前是 error 状态，恢复为 running
                if self.config.get("status") == "error":
                    self._on_status_change(self.config["id"], "running")
            else:
                self.config["status"] = "error"
                self._on_status_change(self.config["id"], "error")
                self._add_log(f"同步失败: {result.message}")
        except Exception as e:
            self.config["status"] = "error"
            self._on_status_change(self.config["id"], "error")
            self._add_log(f"同步异常: {e}")
        finally:
            self._sync_lock.release()


class TaskManager:
    """
    全局任务管理器。
    负责任务配置的持久化（JSON）和 TaskWorker 的生命周期管理。
    所有回调在非 UI 线程中调用；调用方应通过 Qt 信号转发到主线程。
    """

    def __init__(self, on_status_change: Callable,
                 on_log: Callable, on_sync_done: Callable):
        self._on_status = on_status_change
        self._on_log = on_log
        self._on_sync_done = on_sync_done
        self._config_path = _get_config_path()
        self._tasks: dict[str, dict] = {}   # task_id -> config dict
        self._workers: dict[str, TaskWorker] = {}  # task_id -> worker
        self._load_config()

    # ── 配置持久化 ────────────────────────────────────────

    def _load_config(self):
        """从 JSON 文件加载任务配置。"""
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for t in data.get("tasks", []):
                    # 兼容旧配置缺失字段
                    t.setdefault("id", str(uuid.uuid4()))
                    t.setdefault("name", "未命名任务")
                    t.setdefault("branch", "main")
                    t.setdefault("commit_message", "自动同步")
                    t.setdefault("status", "stopped")
                    t.setdefault("last_sync", "从未同步")
                    t.setdefault("logs", [])
                    t.setdefault("local_path", "")
                    t.setdefault("remote_url", "")
                    self._tasks[t["id"]] = t
                logger.info("已加载 %d 个任务配置", len(self._tasks))
            except (json.JSONDecodeError, IOError) as e:
                logger.error("加载配置文件失败: %s", e)

    def _save_config(self):
        """将任务配置写回 JSON 文件。"""
        try:
            # 保存时去掉运行时数据（logs 可从界面获取，不持久化过长的日志）
            save_data = []
            for t in self._tasks.values():
                save_data.append({
                    "id": t["id"],
                    "name": t["name"],
                    "local_path": t["local_path"],
                    "remote_url": t["remote_url"],
                    "branch": t["branch"],
                    "commit_message": t["commit_message"],
                    "status": t.get("status", "stopped"),
                    "last_sync": t.get("last_sync", "从未同步"),
                    # 只保留最近 20 条日志持久化
                    "logs": t.get("logs", [])[-20:],
                })
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump({"tasks": save_data}, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error("保存配置文件失败: %s", e)

    # ── 任务 CRUD ─────────────────────────────────────────

    def get_all_tasks(self) -> list[dict]:
        """返回所有任务配置的副本。"""
        return [dict(t) for t in self._tasks.values()]

    def get_task(self, task_id: str) -> dict | None:
        """获取单个任务配置。"""
        return self._tasks.get(task_id)

    def add_task(self, config: dict) -> str:
        """添加新任务，返回 task_id。"""
        task_id = str(uuid.uuid4())
        config["id"] = task_id
        config.setdefault("name", "未命名任务")
        config.setdefault("branch", "main")
        config.setdefault("commit_message", "自动同步")
        config.setdefault("status", "stopped")
        config.setdefault("last_sync", "从未同步")
        config.setdefault("logs", [])
        self._tasks[task_id] = config
        self._save_config()
        logger.info("已添加任务: %s (%s)", config["name"], task_id)
        return task_id

    def update_task(self, task_id: str, config: dict):
        """更新任务配置。"""
        if task_id not in self._tasks:
            return
        # 保留 id、status、last_sync、logs
        config["id"] = task_id
        config["status"] = self._tasks[task_id].get("status", "stopped")
        config["last_sync"] = self._tasks[task_id].get("last_sync", "从未同步")
        config["logs"] = self._tasks[task_id].get("logs", [])
        self._tasks[task_id] = config
        self._save_config()

    def remove_task(self, task_id: str):
        """删除任务。如果正在运行则先停止。"""
        self.stop_task(task_id)
        self._tasks.pop(task_id, None)
        self._save_config()

    # ── 启停控制 ──────────────────────────────────────────

    def start_task(self, task_id: str):
        """启动指定任务的监控。"""
        config = self._tasks.get(task_id)
        if not config:
            return
        # 如果已在运行，先停止
        if task_id in self._workers:
            self._workers[task_id].stop()
        worker = TaskWorker(config, self._on_status, self._on_log, self._on_sync_done)
        self._workers[task_id] = worker
        worker.start()

    def stop_task(self, task_id: str):
        """停止指定任务。"""
        worker = self._workers.pop(task_id, None)
        if worker:
            worker.stop()

    def start_all(self):
        """启动所有任务。"""
        for task_id in self._tasks:
            self.start_task(task_id)

    def stop_all(self):
        """停止所有任务。"""
        for task_id in list(self._workers.keys()):
            self.stop_task(task_id)

    def shutdown(self):
        """程序退出时调用 —— 停止所有监控。"""
        logger.info("正在关闭所有监控任务...")
        self.stop_all()
