"""
任务配置对话框 —— 添加新任务或编辑已有任务。
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QFileDialog, QDialogButtonBox,
    QLabel, QMessageBox,
)
from PyQt6.QtCore import Qt


class TaskDialog(QDialog):
    """添加 / 编辑同步任务的对话框。"""

    def __init__(self, parent=None, task_config: dict | None = None):
        super().__init__(parent)
        self._editing = task_config is not None
        self.setWindowTitle("编辑同步任务" if self._editing else "添加新任务")
        self.setMinimumWidth(520)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._init_ui(task_config)

    def _init_ui(self, config: dict | None):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # 标题
        title = QLabel("配置同步任务" if config is None else "编辑同步任务")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(title)

        # 表单
        form = QFormLayout()
        form.setSpacing(10)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("给任务起个名字，例如：项目文档同步")
        form.addRow("任务名称：", self.name_edit)

        # 本地路径：输入框 + 浏览按钮
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择要监控的本地文件夹")
        self.path_edit.setReadOnly(True)
        path_row.addWidget(self.path_edit)
        browse_btn = QPushButton("选择文件夹")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_folder)
        path_row.addWidget(browse_btn)
        form.addRow("本地路径：", path_row)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("例如：https://github.com/user/repo.git 或 git@github.com:user/repo.git")
        form.addRow("GitHub 仓库：", self.url_edit)

        self.branch_edit = QLineEdit()
        self.branch_edit.setText("main")
        form.addRow("分支名称：", self.branch_edit)

        self.msg_edit = QLineEdit()
        self.msg_edit.setText("自动同步")
        form.addRow("提交消息：", self.msg_edit)

        layout.addLayout(form)

        # 如果编辑模式，填入现有数据
        if config:
            self.name_edit.setText(config.get("name", ""))
            self.path_edit.setText(config.get("local_path", ""))
            self.url_edit.setText(config.get("remote_url", ""))
            self.branch_edit.setText(config.get("branch", "main"))
            self.msg_edit.setText(config.get("commit_message", "自动同步"))

        layout.addSpacing(8)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择要监控的文件夹")
        if folder:
            self.path_edit.setText(folder)

    def _on_accept(self):
        """校验输入后接受对话框。"""
        name = self.name_edit.text().strip()
        local_path = self.path_edit.text().strip()
        remote_url = self.url_edit.text().strip()
        branch = self.branch_edit.text().strip()
        commit_msg = self.msg_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "提示", "请输入任务名称")
            return
        if not local_path:
            QMessageBox.warning(self, "提示", "请选择本地文件夹路径")
            return
        if not remote_url:
            QMessageBox.warning(self, "提示", "请输入 GitHub 仓库地址")
            return
        if not branch:
            QMessageBox.warning(self, "提示", "请输入分支名称")
            return
        if not commit_msg:
            commit_msg = "自动同步"

        self._result = {
            "name": name,
            "local_path": local_path,
            "remote_url": remote_url,
            "branch": branch,
            "commit_message": commit_msg,
        }
        self.accept()

    def get_result(self) -> dict:
        """返回用户输入的任务配置。"""
        return getattr(self, "_result", {})
