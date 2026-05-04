"""
GitHub 文件夹同步 —— 服务器守护版
无 GUI，纯命令行运行，适合部署在 Linux/Windows 服务器上。

用法:
    python server_monitor.py                     # 使用同目录的 config.json
    python server_monitor.py -c /path/to/config.json   # 指定配置文件
    python server_monitor.py --init              # 生成示例配置文件

依赖（极少）:
    pip install watchdog
"""

import os
import sys
import json
import time
import signal
import logging
import argparse
import subprocess
import threading
from datetime import datetime
from pathlib import Path

# ── 日志 ────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ServerMonitor")

# ── 配置 ────────────────────────────────────────────────

DEBOUNCE_SECONDS = 3
MAX_LOG_ENTRIES = 100
SYNC_LOCK = threading.Lock()  # 全局锁，防并发 git 操作


def get_default_config_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def generate_sample_config(path: str):
    sample = {
        "tasks": [
            {
                "id": "example-001",
                "name": "我的项目文档",
                "local_path": "/home/user/project",
                "remote_url": "https://github.com/username/repo.git",
                "branch": "main",
                "commit_message": "自动同步",
                "status": "stopped",
                "last_sync": "从未同步",
                "logs": []
            }
        ]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sample, f, ensure_ascii=False, indent=2)
    print(f"示例配置文件已生成: {path}")
    print("请编辑此文件，填入你的实际任务信息后重新启动。")


# ── Git 操作 ────────────────────────────────────────────

def _run_git(cwd: str, *args, timeout: int = 60):
    cmd = ["git"] + list(args)
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Git 命令执行超时"
    except FileNotFoundError:
        return -1, "", "未找到 Git，请确认已安装"
    except Exception as e:
        return -1, "", str(e)


def is_git_repo(path: str) -> bool:
    rc, out, _ = _run_git(path, "rev-parse", "--is-inside-work-tree")
    return rc == 0


def has_changes(path: str) -> bool:
    rc, out, _ = _run_git(path, "status", "--porcelain")
    return rc == 0 and len(out) > 0


def _current_branch(path: str) -> str:
    rc, out, _ = _run_git(path, "rev-parse", "--abbrev-ref", "HEAD")
    return out if rc == 0 else ""


def _ensure_branch(path: str, branch: str):
    cur = _current_branch(path)
    if cur and cur != branch:
        _run_git(path, "branch", "-M", branch)
        logger.info("分支 %s -> %s", cur, branch)


def init_repo(path: str, remote_url: str, branch: str):
    rc, _, err = _run_git(path, "init")
    if rc != 0:
        return False, f"git init 失败: {err}"
    rc, out, _ = _run_git(path, "remote", "get-url", "origin")
    if rc == 0:
        _run_git(path, "remote", "set-url", "origin", remote_url)
    else:
        _run_git(path, "remote", "add", "origin", remote_url)
    _ensure_branch(path, branch)
    return True, "ok"


def do_sync(task: dict) -> tuple[bool, str]:
    """执行一次完整的 git 同步。"""
    path = os.path.abspath(task["local_path"])
    remote = task["remote_url"]
    branch = task["branch"]
    msg = task.get("commit_message", "自动同步")

    if not os.path.isdir(path):
        return False, f"目录不存在: {path}"

    # 确保是 git 仓库
    if not is_git_repo(path):
        ok, err = init_repo(path, remote, branch)
        if not ok:
            return False, err
        _run_git(path, "add", "-A")
        _run_git(path, "commit", "-m", "初始提交（由 ServerMonitor 自动创建）")
        _ensure_branch(path, branch)

    # 确保 remote 正确
    rc, cur_remote, _ = _run_git(path, "remote", "get-url", "origin")
    if rc != 0:
        return False, "仓库没有远程地址 origin"
    if cur_remote != remote:
        _run_git(path, "remote", "set-url", "origin", remote)

    # 确保分支名正确
    _ensure_branch(path, branch)

    # 有变更才 add + commit
    committed = False
    if has_changes(path):
        rc, _, err = _run_git(path, "add", "-A")
        if rc != 0:
            return False, f"git add 失败: {err}"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_msg = f"{msg} ({ts})"
        rc, out, err = _run_git(path, "commit", "-m", full_msg)
        if rc == 0:
            committed = True
        elif "nothing to commit" not in (err + out).lower():
            return False, f"git commit 失败: {err or out}"

    # pull
    rc, _, err = _run_git(path, "pull", "--rebase", "origin", branch, timeout=120)
    if rc != 0:
        logger.warning("git pull 失败（继续 push）: %s", err)

    # push
    rc, out, err = _run_git(path, "push", "-u", "origin", branch, timeout=120)
    if rc != 0:
        combined = (err + " " + out).lower()
        if "does not match" in combined:
            _ensure_branch(path, branch)
            rc2, _, err2 = _run_git(path, "push", "-u", "origin", branch, timeout=120)
            if rc2 != 0:
                return False, f"git push 失败: {err2}"
        elif "everything up-to-date" not in combined:
            return False, f"git push 失败: {err or out}"

    if committed:
        return True, "同步成功"
    return True, "已推送"


# ── 监控调度 ────────────────────────────────────────────

class TaskRunner:
    def __init__(self, task: dict):
        self.task = task
        self._debounce_timer: threading.Timer | None = None
        self._stop = threading.Event()
        self._observer = None

    def start(self):
        self._stop.clear()
        # 延迟导入 watchdog（服务器可能未装）
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            path = os.path.abspath(self.task["local_path"])
            if not os.path.isdir(path):
                logger.error("[%s] 目录不存在: %s", self.task["name"], path)
                return

            class Handler(FileSystemEventHandler):
                def __init__(self_, callback):
                    super().__init__()
                    self_._cb = callback

                def on_any_event(self_, event):
                    if not event.is_directory:
                        # 忽略 .git 目录
                        if ".git" not in event.src_path.replace("\\", "/").split("/"):
                            self_._cb()

            def on_change():
                if self._stop.is_set():
                    return
                if self._debounce_timer:
                    self._debounce_timer.cancel()
                self._debounce_timer = threading.Timer(DEBOUNCE_SECONDS, self._do_sync)
                self._debounce_timer.daemon = True
                self._debounce_timer.start()

            handler = Handler(on_change)
            self._observer = Observer()
            self._observer.schedule(handler, path, recursive=True)
            self._observer.start()
            logger.info("[%s] 监控已启动 → %s", self.task["name"], path)

        except ImportError:
            logger.error("[%s] 请安装 watchdog: pip install watchdog", self.task["name"])
        except Exception as e:
            logger.error("[%s] 启动失败: %s", self.task["name"], e)

    def stop(self):
        self._stop.set()
        if self._debounce_timer:
            self._debounce_timer.cancel()
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        logger.info("[%s] 监控已停止", self.task["name"])

    def _do_sync(self):
        if self._stop.is_set():
            return
        if not SYNC_LOCK.acquire(blocking=False):
            return  # 全局只允许一个同步任务同时执行
        try:
            logger.info("[%s] 开始同步...", self.task["name"])
            ok, msg = do_sync(self.task)
            if ok:
                logger.info("[%s] %s", self.task["name"], msg)
            else:
                logger.error("[%s] %s", self.task["name"], msg)
        except Exception as e:
            logger.error("[%s] 异常: %s", self.task["name"], e)
        finally:
            SYNC_LOCK.release()

    def sync_now(self):
        """手动触发立即同步。"""
        if self._debounce_timer:
            self._debounce_timer.cancel()
        threading.Thread(target=self._do_sync, daemon=True).start()


# ── 主函数 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GitHub 文件夹同步 - 服务器守护版")
    parser.add_argument("-c", "--config", help="配置文件路径", default=get_default_config_path())
    parser.add_argument("--init", action="store_true", help="生成示例配置文件")
    args = parser.parse_args()

    if args.init:
        generate_sample_config(args.config)
        return

    # 加载配置
    config_path = args.config
    if not os.path.exists(config_path):
        print(f"配置文件不存在: {config_path}")
        print(f'运行 "python server_monitor.py --init" 生成示例配置文件')
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    tasks = data.get("tasks", [])
    if not tasks:
        print("配置文件中没有任务，请编辑 config.json 添加任务。")
        sys.exit(1)

    # 启动所有任务
    runners: list[TaskRunner] = []
    for t in tasks:
        runner = TaskRunner(t)
        runner.start()
        runners.append(runner)

    logger.info("所有任务已启动，按 Ctrl+C 退出...")

    # 优雅退出
    def shutdown(signum=None, frame=None):
        logger.info("正在停止所有任务...")
        for r in runners:
            r.stop()
        logger.info("已退出")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 保持运行
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
