"""
GitHub 同步监控 —— 程序入口。
- 创建 QApplication
- 初始化 TaskManager（加载配置）
- 自动启动所有任务
- 显示主窗口
- 启动系统托盘（关闭窗口时最小化到托盘，不退出程序）
"""

import sys
import logging
import signal

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QTimer, QSharedMemory
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt

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


# ── 暗色模式样式表 ──────────────────────────────────────

DARK_STYLESHEET = """
QMainWindow, QDialog, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QFrame#taskCard {
    background-color: #2a2a3c;
    border: 1px solid #45475a;
    border-radius: 8px;
}
QLabel {
    color: #cdd6f4;
}
QLineEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
}
QLineEdit:focus {
    border-color: #89b4fa;
}
QTextEdit {
    background-color: #1e1e2e;
    color: #a6adc8;
    border: 1px solid #313244;
    border-radius: 4px;
    font-family: Consolas;
    font-size: 10px;
}
QScrollArea {
    background-color: transparent;
}
QScrollBar:vertical {
    background: #313244;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #585b70;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QPushButton {
    border-radius: 4px;
    padding: 6px 16px;
    font-size: 12px;
}
QMessageBox {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QMessageBox QLabel {
    color: #cdd6f4;
}
QDialogButtonBox QPushButton {
    background: #45475a;
    color: #cdd6f4;
    border: none;
    border-radius: 4px;
    padding: 6px 16px;
}
QDialogButtonBox QPushButton:hover {
    background: #585b70;
}
QFormLayout QLabel {
    color: #a6adc8;
}
"""


def _is_dark_mode() -> bool:
    """检测 Windows 是否开启了深色模式。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except Exception:
        return False


# ── 线程安全的回调桥接 ─────────────────────────────────

class CallbackBridge:
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
    app.setQuitOnLastWindowClosed(False)

    # 暗色模式
    if _is_dark_mode():
        app.setStyleSheet(DARK_STYLESHEET)
        pal = app.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#1e1e2e"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#cdd6f4"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#313244"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#cdd6f4"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#45475a"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#cdd6f4"))
        app.setPalette(pal)

    # 单实例检测
    single_instance = QSharedMemory("GitHubSyncMonitor_Instance")
    if not single_instance.create(1):
        QMessageBox.warning(None, "GitHub 同步监控", "程序已在运行中，请查看系统托盘图标。")
        sys.exit(0)
    app._single_instance = single_instance

    # 1. 创建 TaskManager（加载 config.json）
    bridge = CallbackBridge()
    mgr = TaskManager(
        on_status_change=bridge.on_status_change,
        on_log=bridge.on_log,
        on_sync_done=bridge.on_sync_done,
    )

    # 2. 创建主窗口
    window = MainWindow(mgr, is_dark=_is_dark_mode())
    window.show()

    # 3. 启动时自动运行所有任务
    QTimer.singleShot(500, mgr.start_all)

    # 4. 系统托盘
    def show_window():
        QTimer.singleShot(0, window.show)
        QTimer.singleShot(0, window.activateWindow)
        QTimer.singleShot(0, window.raise_)

    def exit_app():
        QTimer.singleShot(0, app.quit)

    tray = SystemTray(on_show_window=show_window, on_exit=exit_app)
    tray.start(app_name="GitHub 同步监控")

    def _cleanup():
        logger.info("正在退出程序...")
        mgr.shutdown()
        tray.stop()
    app.aboutToQuit.connect(_cleanup)

    # 5. 处理 Ctrl+C
    signal.signal(signal.SIGINT, lambda *_: exit_app())

    logger.info("程序已启动")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
