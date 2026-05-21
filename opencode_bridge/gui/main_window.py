import logging
import os
import re
import time
from glob import glob
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTabWidget, QSystemTrayIcon, QMenu,
    QScrollArea,
)
from PyQt6.QtCore import QTimer, pyqtSignal, QThread, QEvent, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction, QFont

from opencode_bridge.config.settings import load_config, save_config, AppConfig
from opencode_bridge.gui.settings_panel import SettingsPanel
from opencode_bridge.gui.log_panel import LogPanel
from opencode_bridge.monitor.email_monitor import EmailMonitor
from opencode_bridge.monitor.email_sender import send_email
from opencode_bridge.monitor.message_parser import ParsedMessage
from opencode_bridge.openwork.client import OpenWorkClient, scan_opencode_servers, opencode_installed, start_opencode_server

logger = logging.getLogger("MainWindow")


def _find_recent_files(within_secs: int = 60, max_files: int = 5) -> list[str]:
    """Find files modified within the last `within_secs` seconds."""
    exts = ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.webp", "*.txt", "*.pdf", "*.docx", "*.doc", "*.xlsx", "*.xls", "*.csv", "*.zip", "*.rar")
    cutoff = time.time() - within_secs
    found = []
    base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    search_dirs = [base, os.environ.get("TEMP", ""), os.environ.get("TMP", ""),
                   os.path.expanduser("~/Desktop"), os.path.expanduser("~/Downloads")]
    for search_dir in search_dirs:
        if not search_dir or not os.path.isdir(search_dir):
            continue
        for ext in exts:
            for f in glob(os.path.join(search_dir, "**", ext), recursive=True):
                try:
                    if os.path.getmtime(f) >= cutoff:
                        found.append(f)
                except OSError:
                    continue
    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return found[:max_files]


def _extract_file_paths(text: str) -> list[str]:
    """Extract existing file paths from AI response text, supporting any file type."""
    paths = set()
    # Match paths between backticks/quotes (any extension)
    for m in re.finditer(r"""([`'"])([^`'"]+\.[a-zA-Z0-9]{2,})\1""", text):
        p = m.group(2)
        logger.debug("附件匹配[引号]: %s", p)
        if os.path.isfile(p):
            paths.add(os.path.normpath(p))
    # Match raw Windows paths (unquoted)
    for m in re.finditer(r"""([a-zA-Z]:\\[^\s,;)\]}'`"]+\.?[a-zA-Z0-9]{0,4})""", text):
        p = m.group(1).strip("`'\" ")
        logger.debug("附件匹配[Win路径]: %s", p)
        if os.path.isfile(p):
            paths.add(os.path.normpath(p))
    # Match Unix-style paths
    for m in re.finditer(r"""((?:/[^\s/]+)+\.?[a-zA-Z0-9]{0,4})""", text):
        p = m.group(1).strip("`'\" ")
        logger.debug("附件匹配[Unix路径]: %s", p)
        if os.path.isfile(p):
            paths.add(os.path.normpath(p))
    logger.debug("附件路径提取结果: %s", paths)
    return list(paths)


class MainWindow(QMainWindow):
    message_forwarded = pyqtSignal(str, str)  # ok_or_error, detail

    def __init__(self):
        super().__init__()
        logger.info("MainWindow.__init__")
        self.setWindowTitle("OpenCodeBridge")
        self.setMinimumSize(640, 520)

        self._monitor: EmailMonitor = None
        self._ow_client: OpenWorkClient = None
        self._cmd_queue = []
        self._busy = False
        self._last_sender = ""

        self._setup_ui()
        self._setup_tray_icon()
        config = load_config()
        self._settings_panel.load_config(config)
        self._update_ow_client(config)

        self.message_forwarded.connect(self._on_message_forwarded)
        QTimer.singleShot(100, self._auto_detect)

    def _setup_tray_icon(self):
        from PyQt6.QtGui import QPainterPath
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(0x0d, 0x47, 0xa1))
        painter.setBrush(QColor(0x1a, 0x73, 0xe8))
        painter.drawRoundedRect(2, 2, 28, 28, 6, 6)

        pen = painter.pen()
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(QColor(255, 255, 255))
        painter.setPen(QColor(255, 255, 255))
        painter.drawRect(6, 14, 4, 10)
        painter.drawRect(22, 14, 4, 10)
        painter.drawRect(4, 22, 24, 4)

        path = QPainterPath()
        path.moveTo(8, 14)
        path.cubicTo(8, 8, 24, 8, 24, 14)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()

        self._tray_icon = QSystemTrayIcon(QIcon(pixmap), self)
        self._tray_icon.setToolTip("OpenCodeBridge - 邮件监控")

        tray_menu = QMenu()
        self._tray_show_action = QAction("显示/隐藏窗口", self)
        self._tray_show_action.triggered.connect(self._toggle_visible)
        tray_menu.addAction(self._tray_show_action)
        tray_menu.addSeparator()
        self._tray_quit_action = QAction("退出", self)
        self._tray_quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(self._tray_quit_action)

        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.raise_()
            self.activateWindow()

    def _quit_app(self):
        self._stop_monitor()
        if self._ow_client:
            self._ow_client.close()
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def _auto_start_monitor(self):
        self._start_monitor()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self._tabs = QTabWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._settings_panel = SettingsPanel()
        scroll.setWidget(self._settings_panel)
        self._log_panel = LogPanel()
        self._tabs.addTab(scroll, "配置")
        self._tabs.addTab(self._log_panel, "运行日志")
        layout.addWidget(self._tabs)

        ctrl_layout = QHBoxLayout()
        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet("font-weight: bold;")
        ctrl_layout.addWidget(self._status_label)
        ctrl_layout.addStretch()
        self._start_btn = QPushButton("启动监控")
        self._start_btn.clicked.connect(self._toggle_monitor)
        ctrl_layout.addWidget(self._start_btn)
        layout.addLayout(ctrl_layout)

    def _auto_detect(self):
        self._log_panel.info("正在检测本地 OpenCode...")
        oc = scan_opencode_servers()
        servers = oc
        if servers:
            for s in servers:
                self._log_panel.success(f"检测到 {s['type']}: {s['url']}")
            url = servers[0]["url"]
            config = self._settings_panel.get_config()
            config.openwork_url = url
            self._settings_panel.load_config(config)
            self._update_ow_client(config)
            save_config(config)
            self._log_panel.info(f"已连接到 {url}")
            QTimer.singleShot(1000, self._auto_start_monitor)
        elif opencode_installed():
            self._log_panel.info("已安装 opencode CLI，尝试启动服务...")
            ok, msg = start_opencode_server()
            if ok:
                self._log_panel.success(msg)
                QTimer.singleShot(2000, self._auto_detect)
            else:
                self._log_panel.warn(msg)
        else:
            self._log_panel.warn("未检测到 OpenCode，请安装或手动配置")

    def _update_ow_client(self, config: AppConfig):
        if self._ow_client:
            self._ow_client.close()
        self._ow_client = OpenWorkClient(
            base_url=config.openwork_url,
            token=config.token,
            workspace_id=config.workspace_id,
        )

    def _toggle_monitor(self):
        if self._monitor and self._monitor.is_running:
            self._stop_monitor()
        else:
            self._start_monitor()

    def _start_monitor(self):
        config = self._settings_panel.get_config()
        if not config.imap_server or not config.imap_username or not config.imap_password:
            self._log_panel.error("请先填写完整的邮箱配置（IMAP 服务器、账号、密码）")
            return
        if not config.sender:
            self._log_panel.warn("未设置监控发件人，将处理所有发件人的邮件")
        save_config(config)
        self._update_ow_client(config)

        self._monitor = EmailMonitor(
            imap_server=config.imap_server,
            imap_port=config.imap_port,
            username=config.imap_username,
            password=config.imap_password,
            sender=config.sender,
            own_email=config.imap_username,
            command_prefix=config.command_prefix,
            poll_interval=config.poll_interval,
        )
        self._monitor.on_message = self._on_monitor_message
        self._monitor.on_status = self._on_monitor_status

        if not self._monitor.start():
            self._log_panel.error("启动邮件监控失败，请检查邮箱配置")
            return

        self._start_btn.setText("停止监控")
        self._status_label.setText("监控运行中")
        self._status_label.setStyleSheet("font-weight: bold; color: green;")
        self._log_panel.success(f"邮件监控已启动: {config.imap_server}:{config.imap_port}")

    def _stop_monitor(self):
        if self._monitor:
            self._monitor.stop()
            self._monitor = None
        self._start_btn.setText("启动监控")
        self._status_label.setText("已停止")
        self._status_label.setStyleSheet("font-weight: bold; color: red;")
        self._log_panel.info("监控已停止")

    def _on_monitor_status(self, msg: str):
        self._log_panel.info(msg)

    def _on_monitor_message(self, parsed: ParsedMessage):
        cmd = parsed.command
        self._last_sender = parsed.sender
        self._log_panel.info(
            f"检测到来自 [{parsed.sender}] 的命令: {cmd[:60]}"
        )
        if not self._ow_client:
            self._log_panel.warn("OpenCode 客户端未配置")
            return
        self._cmd_queue.append(cmd)
        self._process_queue()

    def _process_queue(self):
        if self._busy or not self._cmd_queue:
            return
        self._busy = True
        cmd = self._cmd_queue.pop(0)
        self._log_panel.info("正在执行...")
        self._status_label.setText("执行中")
        self._status_label.setStyleSheet("font-weight: bold; color: orange;")
        from threading import Thread
        Thread(target=self._forward_cmd, args=(cmd,), daemon=True).start()

    def _forward_cmd(self, command: str):
        try:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._ow_client.send_prompt, command)
                ok, detail = future.result(timeout=600)
            self.message_forwarded.emit("success" if ok else "error", detail)
        except TimeoutError:
            self.message_forwarded.emit("error", "OpenCode 响应超时（600秒），请检查模型状态")
        except Exception as e:
            self.message_forwarded.emit("error", str(e))

    def _on_message_forwarded(self, ok_or_error: str, detail: str):
        self._busy = False
        if ok_or_error == "success":
            self._log_panel.success(f"已转发: {detail[:200]}")
        else:
            self._log_panel.error(f"转发失败: {detail[:200]}")

        # Send reply email if SMTP is configured
        self._send_reply_email(ok_or_error, detail)

        self._status_label.setText("监控运行中")
        self._status_label.setStyleSheet("font-weight: bold; color: green;")
        self._process_queue()

    def _send_reply_email(self, ok_or_error: str, detail: str):
        config = self._settings_panel.get_config()
        if not config.smtp_server:
            return
        if not self._last_sender:
            return

        # Extract email address from sender string like "name" <email>
        to_addr = self._last_sender
        if "<" in to_addr and ">" in to_addr:
            to_addr = to_addr.split("<")[-1].split(">")[0].strip()

        smtp_user = config.smtp_username or config.imap_username
        smtp_pwd = config.smtp_password or config.imap_password
        from_addr = config.smtp_sender or config.smtp_username or config.imap_username

        prefix = "✓ 执行成功" if ok_or_error == "success" else "✗ 执行失败"
        subject = f"{prefix}: OpenCodeBridge 执行结果"
        body = f"命令执行结果:\n\n{detail[:3000]}"

        def _send():
            # Collect attachments: file paths mentioned in AI response + recent files
            attachments = _extract_file_paths(detail)
            attachments.extend(_find_recent_files(60))
            attachments = list(dict.fromkeys(attachments))  # dedup preserving order
            if attachments:
                self._log_panel.info(f"附件 {len(attachments)} 个: {[os.path.basename(p) for p in attachments]}")
            ok, msg = send_email(
                config.smtp_server, config.smtp_port,
                smtp_user, smtp_pwd, from_addr, to_addr,
                subject, body, attachments,
            )
            if ok:
                self._log_panel.success(f"回复邮件: {msg}")
            else:
                self._log_panel.warn(f"回复邮件失败: {msg}")

        from threading import Thread
        Thread(target=_send, daemon=True).start()


