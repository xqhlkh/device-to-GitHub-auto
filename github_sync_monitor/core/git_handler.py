"""
Git 操作模块 —— 封装 git add / commit / push 流程。
不处理身份认证，假定用户已配置好 SSH 或 HTTPS 凭证。
"""

import os
import subprocess
import logging
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
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
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


def _current_branch(local_path: str) -> str:
    """获取当前分支名。"""
    rc, stdout, _ = _run_git(local_path, "rev-parse", "--abbrev-ref", "HEAD")
    return stdout if rc == 0 else ""


def _ensure_branch(local_path: str, branch: str):
    """确保当前分支名是指定名称（不一致则重命名）。"""
    cur = _current_branch(local_path)
    if cur and cur != branch:
        _run_git(local_path, "branch", "-M", branch)
        logger.info("分支已从 %s 重命名为 %s", cur, branch)


def init_repo(local_path: str, remote_url: str, branch: str) -> SyncResult:
    """初始化 Git 仓库、设置远程地址、确保分支名正确。"""
    # git init
    rc, stdout, stderr = _run_git(local_path, "init")
    if rc != 0:
        return SyncResult(False, f"git init 失败: {stderr}")

    # 检查是否已有 remote
    rc, stdout, _ = _run_git(local_path, "remote", "get-url", "origin")
    if rc == 0:
        _run_git(local_path, "remote", "set-url", "origin", remote_url)
    else:
        rc, _, stderr = _run_git(local_path, "remote", "add", "origin", remote_url)
        if rc != 0:
            return SyncResult(False, f"添加远程地址失败: {stderr}")

    # 强制设置分支名（git init 后可能叫 master 而不是 main）
    _ensure_branch(local_path, branch)

    return SyncResult(True, "仓库初始化完成")


def has_changes(local_path: str) -> bool:
    """检查是否有未提交的更改（包括新增、修改、删除）。"""
    rc, stdout, _ = _run_git(local_path, "status", "--porcelain")
    return rc == 0 and len(stdout) > 0


def do_sync(local_path: str, remote_url: str, branch: str,
            commit_message: str) -> SyncResult:
    """
    执行完整的同步流程：
    1. 确认是 git 仓库（否则初始化 + 首次提交）
    2. 确保远程地址和分支名正确
    3. git add -A
    4. git commit
    5. git pull --rebase
    6. git push
    """
    abs_path = os.path.abspath(local_path)

    if not os.path.isdir(abs_path):
        return SyncResult(False, f"本地路径不存在: {abs_path}")

    # ============================================================
    # Step 1: 确保是 git 仓库
    # ============================================================
    if not is_git_repo(abs_path):
        logger.info("目录非 Git 仓库，执行初始化...")
        result = init_repo(abs_path, remote_url, branch)
        if not result.success:
            return result
        # 首次提交所有文件
        _run_git(abs_path, "add", "-A")
        rc, _, stderr = _run_git(abs_path, "commit", "-m",
                                 "初始提交（由 GitHubSyncMonitor 自动创建）")
        # 允许 "nothing to commit" 的情况
        _ensure_branch(abs_path, branch)

    # ============================================================
    # Step 2: 确保 remote origin 和分支名正确
    # ============================================================
    rc, current_remote, _ = _run_git(abs_path, "remote", "get-url", "origin")
    if rc != 0:
        return SyncResult(False, "仓库没有配置远程地址 origin，请检查仓库状态")
    if current_remote != remote_url:
        _run_git(abs_path, "remote", "set-url", "origin", remote_url)
        logger.info("远程地址已更新")

    # 确保本地分支名与配置一致
    _ensure_branch(abs_path, branch)

    # ============================================================
    # Step 3-5: 有变更才 add + commit；无变更仍然继续 push
    # ============================================================
    committed = False
    if has_changes(abs_path):
        rc, stdout, stderr = _run_git(abs_path, "add", "-A")
        if rc != 0:
            return SyncResult(False, f"git add 失败: {stderr}")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"{commit_message} ({ts})"
        rc, stdout, stderr = _run_git(abs_path, "commit", "-m", msg)
        if rc != 0:
            combined = (stderr + " " + stdout).lower()
            if "nothing to commit" in combined or "nothing added to commit" in combined:
                # 没有新变更，继续尝试 push（可能之前有未推送的提交）
                pass
            else:
                return SyncResult(False, f"git commit 失败: {stderr or stdout}")
        else:
            committed = True

    # ============================================================
    # Step 6: git pull --rebase（先拉取远端，避免 non-fast-forward）
    # ============================================================
    _do_pull_rebase(abs_path, branch)

    # ============================================================
    # Step 7: git push（带重试）
    # ============================================================
    for attempt in range(2):
        rc, stdout, stderr = _run_git(abs_path, "push", "-u", "origin", branch, timeout=120)
        if rc == 0:
            break
        combined = (stderr + " " + stdout).lower()
        if "does not match any" in combined or "does not exist" in combined:
            _ensure_branch(abs_path, branch)
            continue
        elif "everything up-to-date" in combined:
            break
        elif "non-fast-forward" in combined or "rejected" in combined or "behind" in combined:
            # 远端有本地没有的提交，强制 rebase 后再推
            logger.warning("远端有冲突提交，执行强制 rebase...")
            _do_pull_rebase(abs_path, branch, force=True)
            continue
        else:
            return SyncResult(False, f"git push 失败: {stderr or stdout}")
    else:
        # 两次重试都失败
        return SyncResult(False, f"git push 失败: {stderr or stdout}")

    if committed:
        return SyncResult(True, "同步成功")
    return SyncResult(True, "已推送")


def _do_pull_rebase(local_path: str, branch: str, force: bool = False):
    """执行 git pull --rebase，失败时尝试更激进策略。"""
    # 策略 1: 普通 pull --rebase
    args = ["pull", "--rebase"]
    if force:
        args += ["-X", "theirs"]  # 冲突时以远端为准
    rc, stdout, stderr = _run_git(local_path, *args, "origin", branch, timeout=120)
    if rc == 0:
        return

    # 策略 2: fetch + rebase（允许无关历史）
    logger.warning("pull 失败，尝试 fetch + rebase...")
    rc, _, _ = _run_git(local_path, "fetch", "origin", branch, timeout=120)
    if rc == 0:
        rebase_args = ["rebase", f"origin/{branch}"]
        if force:
            rebase_args += ["-X", "theirs"]
        rc2, _, err2 = _run_git(local_path, *rebase_args, timeout=120)
        if rc2 == 0:
            return
        # rebase 失败则放弃 rebase，回到合并前的状态
        _run_git(local_path, "rebase", "--abort")
        logger.warning("rebase 也失败: %s", err2)

    # 策略 3: 最后尝试 merge（以远端为准）
    logger.warning("尝试 merge 策略...")
    merge_args = ["merge", f"origin/{branch}", "-X", "theirs", "--allow-unrelated-histories"]
    _run_git(local_path, *merge_args, timeout=120)
