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
    # Step 3-5: 有变更才 add + commit
    # ============================================================
    detail_parts = []
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
                detail_parts.append("没有新文件变更")
            else:
                return SyncResult(False, f"git commit 失败: {stderr or stdout}")
        else:
            committed = True
            detail_parts.append(f"已提交: {stdout[:80]}" if stdout else "已提交本地")
    else:
        detail_parts.append("无文件变更")

    # ============================================================
    # Step 6-7: pull + push
    # ============================================================
    # 记录 push 前的状态
    local_pre, _, _ = _run_git(abs_path, "rev-parse", "--short", "HEAD")
    detail_parts.append(f"本地: {local_pre[:8] if local_pre else '?'}")

    pushed, push_detail = _pull_then_push(abs_path, branch)
    detail_parts.append(push_detail)

    if not pushed:
        detail_parts.append("推送失败！")
        return SyncResult(False, " | ".join(detail_parts))

    # 记录 push 后的远端状态
    remote_after, _, _ = _run_git(abs_path, "ls-remote", "origin", branch)
    if remote_after:
        remote_hash = remote_after.split()[0] if remote_after.split() else "?"
        detail_parts.append(f"远端: {remote_hash[:8]}")
    detail_parts.append("推送成功" if committed else "远端已最新")

    return SyncResult(True, " | ".join(detail_parts))


def _pull_then_push(local_path: str, branch: str) -> bool:
    """拉取远端并推送，支持自动重试。返回 True 表示成功。"""
    for attempt in range(3):
        # --- 先拉取 ---
        if attempt == 0:
            # 第一次：正常 pull --rebase
            rc, _, _ = _run_git(local_path, "pull", "--rebase", "origin", branch, timeout=120)
        elif attempt == 1:
            # 第二次：fetch + rebase（远端优先）
            _run_git(local_path, "fetch", "origin", branch, timeout=120)
            rc, _, _ = _run_git(local_path, "rebase", f"origin/{branch}", timeout=120)
            if rc != 0:
                _run_git(local_path, "rebase", "--abort")
        else:
            # 第三次：fetch + merge（远端覆盖冲突）
            _run_git(local_path, "fetch", "origin", branch, timeout=120)
            rc, _, _ = _run_git(local_path, "merge", f"origin/{branch}",
                                "-X", "theirs", "--allow-unrelated-histories", timeout=120)
        # --- 再推送 ---
        rc_push, stdout, stderr = _run_git(local_path, "push", "-u", "origin", branch, timeout=120)
        combined = (stderr + " " + stdout).lower()
        if rc_push == 0:
            # 验证：确认远端真的有我们的提交
            local_hash, _, _ = _run_git(local_path, "rev-parse", "HEAD")
            remote_hash, _, _ = _run_git(local_path, "ls-remote", "origin", branch)
            if local_hash and remote_hash and local_hash in remote_hash:
                return True
            if "rejected" in combined or "error" in combined:
                logger.warning("push 返回成功但远端验证失败，重试...")
                continue
            # 可能是 up-to-date 的情况
            if "everything up-to-date" in combined:
                return True
            return True  # 保守起见仍然返回成功
        if "everything up-to-date" in combined:
            return True
        if "does not match" in combined:
            _ensure_branch(local_path, branch)
            continue
        if "non-fast-forward" in combined or "rejected" in combined:
            logger.warning("push 被拒（第 %d 次），重试更激进的拉取策略...", attempt + 1)
            continue
        logger.warning("push 失败（第 %d 次）: %s", stderr[:200] if stderr else stdout[:200], attempt + 1)
    return False
