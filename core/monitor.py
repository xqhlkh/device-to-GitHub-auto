"""
文件监控模块 —— 基于 watchdog 监听文件夹的文件变更。
检测到变化时触发回调，交由上层做防抖 + Git 同步。
"""

import os
import logging
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger("Monitor")

# 忽略的文件/文件夹模式（减少不必要的触发）
IGNORE_PATTERNS = [
    ".git",
    "__pycache__",
    ".DS_Store",
    "Thumbs.db",
    "~$",          # Office 临时文件
    ".~lock.",     # LibreOffice 锁文件
]


def _should_ignore(path: str) -> bool:
    """判断路径是否应被忽略（例如 .git 目录内的变化）。"""
    normalized = path.replace("\\", "/")
    for pattern in IGNORE_PATTERNS:
        if f"/{pattern}/" in normalized or f"/{pattern}" in normalized or normalized.endswith(f"/{pattern}"):
            return True
        if pattern in normalized.split("/"):
            return True
    return False


class FileChangeHandler(FileSystemEventHandler):
    """watchdog 事件处理器 —— 将任何文件变更转发给回调函数。"""

    def __init__(self, on_change_callback):
        super().__init__()
        self._callback = on_change_callback  # callable, 无参数

    def on_created(self, event):
        if not event.is_directory and not _should_ignore(event.src_path):
            self._callback()

    def on_modified(self, event):
        if not event.is_directory and not _should_ignore(event.src_path):
            self._callback()

    def on_deleted(self, event):
        if not event.is_directory and not _should_ignore(event.src_path):
            self._callback()

    def on_moved(self, event):
        if not event.is_directory:
            if not _should_ignore(event.src_path) or not _should_ignore(event.dest_path):
                self._callback()


class FolderMonitor:
    """
    对单个文件夹启动 watchdog 监控。
    检测到变化后调用 on_change 回调（在 watchdog 线程中调用，非 UI 线程）。
    """

    def __init__(self, folder_path: str, on_change):
        self._path = os.path.abspath(folder_path)
        self._on_change = on_change
        self._observer: Observer | None = None
        self._handler: FileChangeHandler | None = None

    def start(self):
        """启动监控。"""
        if self._observer is not None:
            return  # 已在运行

        if not os.path.isdir(self._path):
            raise FileNotFoundError(f"监控目录不存在: {self._path}")

        self._handler = FileChangeHandler(self._on_change)
        self._observer = Observer()
        self._observer.schedule(self._handler, self._path, recursive=True)
        self._observer.start()
        logger.info("已开始监控: %s", self._path)

    def stop(self):
        """停止监控。"""
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=5)
        self._observer = None
        self._handler = None
        logger.info("已停止监控: %s", self._path)

    @property
    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()
