"""
Git 操作模块 —— 封装 git add / commit / push 流程。
不处理身份认证，假定用户已配置好 SSH 或 HTTPS 凭证。
"""

import os
import subprocess
import logging
import threading
from datetime import datetime

logger = logging.getLogger("GitHandler")


class SyncResult:
    """同步操作的结果封装。"""
    def __init__(self, success: bool, message: str):
        self.success = success
        self.message = message


def _run_git(cwd: str, *args, timeout: int = 60) -> tuple[int, str, str]:
    """
    在指定目录执行 git 命令。
    返回 (returncode, stdout, stderr)。
    """
    cmd = ["git"] + list(args)
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Git 命令执行超时"
    except FileNotFoundError:
        return -1, "", "未找到 Git，请确认已安装 Git 并加入 PATH 环境变量"
    except Exception as e:
        return -1, "", str(e)


def is_git_repo(local_path: str) -> bool:
    """判断目录是否已经是 Git 仓库。"""
    rc, stdout, _ = _run_git(local_path, "rev-parse", "--is-inside-work-tree")
    return rc == 0


def init_repo(local_path: str, remote_url: str) -> SyncResult:
    """初始化 Git 仓库并设置远程地址。"""
    steps = []

    # git init
    rc, stdout, stderr = _run_git(local_path, "init")
    if rc != 0:
        return SyncResult(False, f"git init 失败: {stderr}")
    steps.append("git init 成功")

    # 检查是否已有 remote
    rc, stdout, _ = _run_git(local_path, "remote", "get-url", "origin")
    if rc == 0:
        # 已有 origin，更新 URL
        rc, _, stderr = _run_git(local_path, "remote", "set-url", "origin", remote_url)
        if rc != 0:
            return SyncResult(False, f"更新远程地址失败: {stderr}")
        steps.append("更新远程地址 origin")
    else:
        # 添加 origin
        rc, _, stderr = _run_git(local_path, "remote", "add", "origin", remote_url)
        if rc != 0:
            return SyncResult(False, f"添加远程地址失败: {stderr}")
        steps.append("添加远程地址 origin")

    return SyncResult(True, "; ".join(steps))


def has_changes(local_path: str) -> bool:
    """检查是否有未提交的更改（包括新增、修改、删除）。"""
    rc, stdout, _ = _run_git(local_path, "status", "--porcelain")
    return rc == 0 and len(stdout) > 0


def do_sync(local_path: str, remote_url: str, branch: str,
            commit_message: str) -> SyncResult:
    """
    执行完整的同步流程：
    1. 确认是 git 仓库（否则初始化）
    2. git add -A
    3. git commit
    4. git pull --rebase（避免冲突）
    5. git push
    """
    abs_path = os.path.abspath(local_path)

    if not os.path.isdir(abs_path):
        return SyncResult(False, f"本地路径不存在: {abs_path}")

    # ---- Step 1: 确保是 git 仓库 ----
    if not is_git_repo(abs_path):
        logger.info("目录非 Git 仓库，执行初始化...")
        result = init_repo(abs_path, remote_url)
        if not result.success:
            return result
        # 首次提交需要先创建一个初始提交
        rc, _, _ = _run_git(abs_path, "add", "-A")
        rc, _, stderr = _run_git(abs_path, "commit", "-m", "初始提交（由 GitHubSyncMonitor 自动创建）")
        # 允许 "nothing to commit" 的情况

    # ---- Step 2: 确保 remote origin 正确 ----
    rc, current_remote, _ = _run_git(abs_path, "remote", "get-url", "origin")
    if rc != 0:
        return SyncResult(False, "仓库没有配置远程地址 origin")
    if current_remote.strip() != remote_url.strip():
        _run_git(abs_path, "remote", "set-url", "origin", remote_url)
        logger.info("远程地址已更新为 %s", remote_url)

    # ---- Step 3: 检查是否有变更 ----
    if not has_changes(abs_path):
        return SyncResult(True, "没有检测到文件变更，跳过同步")

    # ---- Step 4: git add -A ----
    rc, stdout, stderr = _run_git(abs_path, "add", "-A")
    if rc != 0:
        return SyncResult(False, f"git add 失败: {stderr}")

    # ---- Step 5: git commit ----
    msg = f"{commit_message} ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
    rc, stdout, stderr = _run_git(abs_path, "commit", "-m", msg)
    if rc != 0:
        # "nothing to commit" 不算错误
        if "nothing to commit" in stderr.lower() or "nothing to commit" in stdout.lower():
            return SyncResult(True, "没有需要提交的变更")
        return SyncResult(False, f"git commit 失败: {stderr}")

    # ---- Step 6: git pull --rebase ----
    rc, stdout, stderr = _run_git(abs_path, "pull", "--rebase", "origin", branch, timeout=120)
    if rc != 0:
        # pull 失败不中断，尝试继续 push（可能是新仓库或无远端提交）
        logger.warning("git pull 失败（将继续 push）: %s", stderr)

    # ---- Step 7: git push ----
    rc, stdout, stderr = _run_git(abs_path, "push", "-u", "origin", branch, timeout=120)
    if rc != 0:
        return SyncResult(False, f"git push 失败: {stderr}")

    return SyncResult(True, "同步成功")
