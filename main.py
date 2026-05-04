"""
GitHub 同步监控 —— 程序入口。
- 创建 QApplication
- 初始化 TaskManager（加载配置）
- 显示主窗口
- 启动系统托盘（关闭窗口时最小化到托盘，不退出程序）
"""

import sys
import logging
import signal

import os
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QTimer, QSharedMemory

from core.task_manager import TaskManager
from ui.main_window import MainWindow
from ui.tray_icon import SystemTray

# ── 日志配置 ────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Main")


# ── 线程安全的回调桥接 ─────────────────────────────────

class CallbackBridge:
    """
    TaskManager 的回调在后台线程中触发。
    此桥接将回调安全地记录日志（UI 由定时器轮询 TaskManager 状态刷新）。
    """

    def on_status_change(self, task_id: str, status: str):
        logger.debug("任务 %s 状态变更 -> %s", task_id, status)

    def on_log(self, task_id: str, message: str):
        logger.debug("任务 %s 日志: %s", task_id, message)

    def on_sync_done(self, task_id: str, timestamp: str):
        logger.info("任务 %s 同步完成: %s", task_id, timestamp)


# ── 主函数 ──────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GitHub 同步监控")
    app.setQuitOnLastWindowClosed(False)  # 关闭窗口不退出程序

    # 单实例检测：如果已有实例在运行，弹窗提示并退出
    single_instance = QSharedMemory("GitHubSyncMonitor_Instance")
    if not single_instance.create(1):
        QMessageBox.warning(None, "GitHub 同步监控", "程序已在运行中，请查看系统托盘图标。")
        sys.exit(0)
    app._single_instance = single_instance  # 防止被垃圾回收

    # 1. 创建 TaskManager（加载 config.json）
    bridge = CallbackBridge()
    mgr = TaskManager(
        on_status_change=bridge.on_status_change,
        on_log=bridge.on_log,
        on_sync_done=bridge.on_sync_done,
    )

    # 2. 创建主窗口
    window = MainWindow(mgr)
    window.show()

    # 3. 系统托盘（回调在 pystray 线程中执行，需用 QTimer 转到主线程）
    def show_window():
        QTimer.singleShot(0, window.show)
        QTimer.singleShot(0, window.activateWindow)
        QTimer.singleShot(0, window.raise_)

    def exit_app():
        # 只用 app.quit()，清理工作放在 aboutToQuit 中防止死锁
        QTimer.singleShot(0, app.quit)

    tray = SystemTray(on_show_window=show_window, on_exit=exit_app)
    tray.start(app_name="GitHub 同步监控")

    # 程序退出前清理
    def _cleanup():
        logger.info("正在退出程序...")
        mgr.shutdown()
        tray.stop()
    app.aboutToQuit.connect(_cleanup)

    # 4. 处理 Ctrl+C
    signal.signal(signal.SIGINT, lambda *_: exit_app())

    logger.info("程序已启动")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
