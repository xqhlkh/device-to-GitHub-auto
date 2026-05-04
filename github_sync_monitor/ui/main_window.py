"""
主窗口界面 —— 显示所有任务卡片，支持启动 / 停止 / 手动同步 / 编辑 / 删除。
关闭窗口时最小化到托盘，不退出程序。
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QLabel, QFrame, QTextEdit, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QCloseEvent

from core.task_manager import TaskManager
from ui.task_dialog import TaskDialog


STATUS_COLORS = {
    "running":  ("#27ae60", "运行中"),
    "stopped":  ("#95a5a6", "已停止"),
    "error":    ("#e74c3c", "错误"),
}


class TaskCard(QFrame):
    """单张任务卡片。"""

    sig_start_stop = pyqtSignal(str)
    sig_sync_now = pyqtSignal(str)
    sig_edit = pyqtSignal(str)
    sig_delete = pyqtSignal(str)

    def __init__(self, task: dict, is_dark: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("taskCard")
        self._dark = is_dark
        self._task_id = task["id"]
        self._status = task.get("status", "stopped")
        self._init_ui(task)

    def _card_bg(self) -> str:
        return "#2a2a3c" if self._dark else "#ffffff"

    def _border(self) -> str:
        return "#45475a" if self._dark else "#e0e0e0"

    def _info_color(self) -> str:
        return "#a6adc8" if self._dark else "#7f8c8d"

    def _log_bg(self) -> str:
        return "#1e1e2e" if self._dark else "#f9f9f9"

    def _log_border(self) -> str:
        return "#313244" if self._dark else "#eee"

    def _log_text(self) -> str:
        return "#a6adc8" if self._dark else "#555"

    def _btn_default(self) -> str:
        if self._dark:
            return "background: #45475a; color: #cdd6f4; border: 1px solid #585b70; border-radius: 4px; padding: 6px 14px; font-size: 12px;"
        return "background: #ecf0f1; color: #2c3e50; border: 1px solid #bdc3c7; border-radius: 4px; padding: 6px 14px; font-size: 12px;"

    def _btn_danger(self) -> str:
        return "background: #e74c3c; color: white; border: none; border-radius: 4px; padding: 6px 14px; font-size: 12px;"

    def _btn_success(self) -> str:
        return "background: #27ae60; color: white; border: none; border-radius: 4px; padding: 6px 14px; font-size: 12px;"

    def _btn_sync(self) -> str:
        return "background: #3498db; color: white; border: none; border-radius: 4px; padding: 6px 14px; font-size: 12px;"

    def _init_ui(self, task: dict):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 10)
        main_layout.setSpacing(6)

        self.setStyleSheet(
            f"QFrame#taskCard {{ background: {self._card_bg()}; "
            f"border: 1px solid {self._border()}; border-radius: 8px; }}"
        )

        # ── 第一行：任务名称 + 状态标签 ──
        header = QHBoxLayout()
        name_label = QLabel(task.get("name", "未命名"))
        name_font = QFont()
        name_font.setPointSize(12)
        name_font.setBold(True)
        name_label.setFont(name_font)
        header.addWidget(name_label)
        header.addStretch()

        self._status_label = QLabel()
        self._status_label.setStyleSheet(
            "padding: 2px 10px; border-radius: 10px; font-size: 11px; font-weight: bold;"
        )
        header.addWidget(self._status_label)
        main_layout.addLayout(header)

        # ── 信息行 ──
        info_lines = [
            f"本地路径: {task.get('local_path', '未设置')}",
            f"远程仓库: {task.get('remote_url', '未设置')}  |  分支: {task.get('branch', 'main')}",
            f"最后同步: {task.get('last_sync', '从未同步')}",
        ]
        for line in info_lines:
            lbl = QLabel(line)
            lbl.setStyleSheet(f"color: {self._info_color()}; font-size: 11px;")
            lbl.setWordWrap(True)
            main_layout.addWidget(lbl)

        # ── 日志区域 ──
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumHeight(100)
        self._log_view.setMinimumHeight(60)
        self._log_view.setStyleSheet(
            f"background: {self._log_bg()}; border: 1px solid {self._log_border()}; "
            f"border-radius: 4px; font-family: Consolas; font-size: 10px; "
            f"color: {self._log_text()};"
        )
        self._log_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        logs = task.get("logs", [])
        self._log_view.setPlainText("\n".join(logs[-8:]) if logs else "暂无日志")
        # 滚到底部
        cursor = self._log_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._log_view.setTextCursor(cursor)
        main_layout.addWidget(self._log_view)

        # ── 按钮行 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._start_btn = QPushButton()
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.clicked.connect(lambda: self.sig_start_stop.emit(self._task_id))

        self._sync_btn = QPushButton("立即同步")
        self._sync_btn.setStyleSheet(self._btn_sync())
        self._sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sync_btn.clicked.connect(lambda: self.sig_sync_now.emit(self._task_id))

        edit_btn = QPushButton("编辑")
        edit_btn.setStyleSheet(self._btn_default())
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.clicked.connect(lambda: self.sig_edit.emit(self._task_id))

        delete_btn = QPushButton("删除")
        delete_btn.setStyleSheet(self._btn_danger())
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.clicked.connect(lambda: self.sig_delete.emit(self._task_id))

        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._sync_btn)
        btn_row.addStretch()
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(delete_btn)
        main_layout.addLayout(btn_row)

        self._update_status_ui(task.get("status", "stopped"))

    def _update_status_ui(self, status: str):
        self._status = status
        color, text = STATUS_COLORS.get(status, ("#95a5a6", status))
        self._status_label.setText(text)
        self._status_label.setStyleSheet(
            f"background: {color}; color: white; padding: 2px 10px; "
            f"border-radius: 10px; font-size: 11px; font-weight: bold;"
        )
        if status == "running":
            self._start_btn.setText("停止")
            self._start_btn.setStyleSheet(self._btn_danger())
        else:
            self._start_btn.setText("启动")
            self._start_btn.setStyleSheet(self._btn_success())

    def update_state(self, task: dict):
        status = task.get("status", "stopped")
        self._update_status_ui(status)
        for lbl in self.findChildren(QLabel):
            if lbl.text().startswith("最后同步:"):
                lbl.setText(f"最后同步: {task.get('last_sync', '从未同步')}")
                break
        logs = task.get("logs", [])
        scrollbar = self._log_view.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 10
        self._log_view.setPlainText("\n".join(logs[-8:]) if logs else "暂无日志")
        if was_at_bottom:
            cursor = self._log_view.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._log_view.setTextCursor(cursor)

    @property
    def task_id(self) -> str:
        return self._task_id


class MainWindow(QMainWindow):
    """主窗口。"""

    def __init__(self, task_manager: TaskManager, is_dark: bool = False):
        super().__init__()
        self._mgr = task_manager
        self._dark = is_dark
        self._cards: dict[str, TaskCard] = {}
        self.setWindowTitle("GitHub 同步监控")
        self.setMinimumSize(720, 520)
        self.resize(800, 640)

        screen = self.screen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

        self._init_ui()
        self._refresh_all_cards()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_card_states)
        self._refresh_timer.start(1000)

    def _top_bg(self) -> str:
        return "#f0f0f5" if not self._dark else "transparent"

    def _status_bar_color(self) -> str:
        return "#7f8c8d" if not self._dark else "#6c7086"

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        title = QLabel("同步任务列表")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        top_row.addWidget(title)
        top_row.addStretch()

        add_btn = QPushButton("+ 添加新任务")
        add_btn.setStyleSheet(
            "QPushButton { background: #3498db; color: white; border: none; "
            "border-radius: 4px; padding: 8px 20px; font-size: 13px; }"
            "QPushButton:hover { background: #2980b9; }"
        )
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._on_add_task)
        top_row.addWidget(add_btn)
        layout.addLayout(top_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self._card_container = QWidget()
        self._card_container.setStyleSheet("background: transparent;")
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setSpacing(10)
        self._card_layout.setContentsMargins(0, 0, 0, 0)

        scroll.setWidget(self._card_container)
        layout.addWidget(scroll, stretch=1)

        self._status_bar = QLabel("就绪")
        self._status_bar.setStyleSheet(
            f"color: {self._status_bar_color()}; font-size: 11px; padding: 4px;"
        )
        layout.addWidget(self._status_bar)

    # ── 卡片管理 ─────────────────────────────────────────

    def _refresh_all_cards(self):
        while self._card_layout.count():
            item = self._card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        tasks = self._mgr.get_all_tasks()
        if not tasks:
            empty_lbl = QLabel(
                '暂无同步任务。\n点击右上角 "+ 添加新任务" 按钮开始使用。'
            )
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            c = "#6c7086" if self._dark else "#bdc3c7"
            empty_lbl.setStyleSheet(f"color: {c}; font-size: 14px; padding: 40px;")
            self._cards["__empty__"] = empty_lbl
            self._card_layout.addWidget(empty_lbl)
        else:
            for task in tasks:
                card = self._create_card(task)
                self._cards[task["id"]] = card
                self._card_layout.addWidget(card)

        self._card_layout.addStretch()
        self._update_status_bar()

    def _create_card(self, task: dict) -> TaskCard:
        card = TaskCard(task, is_dark=self._dark)
        card.sig_start_stop.connect(self._on_start_stop)
        card.sig_sync_now.connect(self._on_sync_now)
        card.sig_edit.connect(self._on_edit)
        card.sig_delete.connect(self._on_delete)
        return card

    def _refresh_card_states(self):
        for task_id, card in self._cards.items():
            if task_id == "__empty__":
                continue
            task = self._mgr.get_task(task_id)
            if task:
                card.update_state(task)
        self._update_status_bar()

    def _update_status_bar(self):
        tasks = self._mgr.get_all_tasks()
        running = sum(1 for t in tasks if t.get("status") == "running")
        total = len(tasks)
        self._status_bar.setText(f"共 {total} 个任务 | {running} 个运行中")

    # ── 操作处理 ─────────────────────────────────────────

    def _on_add_task(self):
        dlg = TaskDialog(self)
        if dlg.exec() == TaskDialog.DialogCode.Accepted:
            config = dlg.get_result()
            task_id = self._mgr.add_task(config)
            self._refresh_all_cards()
            self._mgr.start_task(task_id)
            self._status_bar.setText(f"已添加并启动: {config['name']}")

    def _on_edit(self, task_id: str):
        task = self._mgr.get_task(task_id)
        if not task:
            return
        dlg = TaskDialog(self, task_config=task)
        if dlg.exec() == TaskDialog.DialogCode.Accepted:
            config = dlg.get_result()
            self._mgr.update_task(task_id, config)
            self._refresh_all_cards()

    def _on_delete(self, task_id: str):
        task = self._mgr.get_task(task_id)
        name = task.get("name", "未知") if task else "未知"
        reply = QMessageBox.question(
            self, "确认删除",
            f'确定要删除任务 "{name}" 吗？\n此操作不可恢复。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._mgr.remove_task(task_id)
            self._refresh_all_cards()

    def _on_start_stop(self, task_id: str):
        task = self._mgr.get_task(task_id)
        if not task:
            return
        if task.get("status") == "running":
            self._mgr.stop_task(task_id)
        else:
            self._mgr.start_task(task_id)

    def _on_sync_now(self, task_id: str):
        """手动触发立即同步。"""
        self._mgr.sync_now(task_id)

    # ── 窗口关闭 → 最小化到托盘 ─────────────────────────

    def closeEvent(self, event: QCloseEvent):
        event.ignore()
        self.hide()
