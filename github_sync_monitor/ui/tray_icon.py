"""
系统托盘模块 —— 使用 pystray 实现最小化到 Windows 托盘。
托盘图标右键菜单：显示主界面 / 退出程序。
"""

import logging
import threading
from PIL import Image, ImageDraw
import pystray

logger = logging.getLogger("TrayIcon")


def _create_tray_image(size: int = 64) -> Image.Image:
    """用 Pillow 生成一个简洁的同步图标（圆形箭头风格）。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = size // 8
    cx, cy = size // 2, size // 2
    r = size // 2 - margin

    # 外圈圆环
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        outline=(70, 130, 180, 255),
        width=max(2, size // 16),
    )

    # 中心圆点
    dot_r = r // 4
    draw.ellipse(
        [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
        fill=(70, 130, 180, 255),
    )

    # 绘制两个弧形箭头（简化的同步图标）
    arrow_color = (70, 130, 180, 255)
    arrow_w = max(2, size // 20)

    # 顶部弧线箭头（顺时针）
    arc_bbox1 = [margin + r // 3, margin + r // 3,
                 size - margin - r // 3, size - margin - r // 3]
    draw.arc(arc_bbox1, start=180, end=270, fill=arrow_color, width=arrow_w)
    # 箭头头部（右上角小三角）
    tip_x = arc_bbox1[2]
    tip_y = arc_bbox1[1] + (arc_bbox1[3] - arc_bbox1[1]) // 8
    draw.polygon([
        (tip_x, tip_y),
        (tip_x + arrow_w * 3, tip_y - arrow_w * 2),
        (tip_x + arrow_w * 3, tip_y + arrow_w * 2),
    ], fill=arrow_color)

    # 底部弧线箭头（逆时针）
    arc_bbox2 = [margin + r // 5, margin + r // 5,
                 size - margin - r // 5, size - margin - r // 5]
    draw.arc(arc_bbox2, start=0, end=90, fill=arrow_color, width=arrow_w)
    # 箭头头部（左下角小三角）
    tip_x2 = arc_bbox2[0]
    tip_y2 = arc_bbox2[3] - (arc_bbox2[3] - arc_bbox2[1]) // 8
    draw.polygon([
        (tip_x2, tip_y2),
        (tip_x2 - arrow_w * 3, tip_y2 - arrow_w * 2),
        (tip_x2 - arrow_w * 3, tip_y2 + arrow_w * 2),
    ], fill=arrow_color)

    return img


class SystemTray:
    """Windows 系统托盘图标管理。"""

    def __init__(self, on_show_window, on_exit):
        self._on_show = on_show_window
        self._on_exit = on_exit
        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None

    def start(self, app_name: str = "GitHub 同步监控"):
        """启动系统托盘图标（在独立线程中运行）。"""
        if self._icon is not None:
            return

        image = _create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("显示主界面", self._on_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出程序", self._on_exit),
        )
        self._icon = pystray.Icon(
            name=app_name,
            title=app_name,
            icon=image,
            menu=menu,
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        logger.info("系统托盘已启动")

    def stop(self):
        """停止系统托盘。"""
        if self._icon:
            self._icon.stop()
            self._icon = None
        logger.info("系统托盘已停止")

    def notify(self, title: str, message: str):
        """弹出通知气泡。"""
        if self._icon and hasattr(self._icon, "notify"):
            try:
                self._icon.notify(message, title)
            except Exception:
                pass
