import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QSpinBox, QPushButton, QGroupBox, QLabel,
    QDialog, QDialogButtonBox, QListWidget, QListWidgetItem,
    QCheckBox,
)
from PyQt6.QtCore import pyqtSignal
from opencode_bridge.config.settings import AppConfig, save_config, set_auto_start
from opencode_bridge.monitor.email_monitor import test_imap_connection
from opencode_bridge.monitor.email_sender import test_smtp_connection, send_email
from opencode_bridge.openwork.client import scan_openwork_servers, scan_opencode_servers, start_opencode_server, opencode_installed

logger = logging.getLogger("SettingsPanel")


class ServerDetectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("检测结果")
        self.setMinimumSize(500, 300)
        layout = QVBoxLayout(self)
        self._list = QListWidget()
        layout.addWidget(self._list)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self.accept)
        btn.rejected.connect(self.reject)
        layout.addWidget(btn)
        self._servers = []

    def set_servers(self, servers: list[dict]):
        self._servers = servers
        self._list.clear()
        if not servers:
            msg = "未检测到本地 OpenWork/OpenCode 服务"
            if opencode_installed():
                msg += "，但已安装 opencode CLI（可作为备用）"
            QListWidgetItem(f"\u26a0 {msg}", self._list)
            return
        for s in servers:
            t = s["type"]
            v = s.get("version", "")
            url = s.get("url", "")
            ver = f" v{v}" if v else ""
            QListWidgetItem(f"\u2713 [{t}]{ver}  {url}", self._list)

    def selected_url(self) -> str:
        row = self._list.currentRow()
        if 0 <= row < len(self._servers):
            return self._servers[row].get("url", "")
        return ""


class SettingsPanel(QWidget):
    test_result = pyqtSignal(bool, str)
    smtp_test_result = pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = None
        self.test_result.connect(self._on_test_result)
        self.smtp_test_result.connect(self._on_smtp_test_result)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- 邮箱监控配置 ---
        mail_group = QGroupBox("邮箱监控配置")
        mf = QFormLayout(mail_group)
        mf.setVerticalSpacing(8)

        self._sender_input = QLineEdit()
        self._sender_input.setPlaceholderText("只处理此发件人的邮件，留空则不限制")
        mf.addRow("被监控发件人:", self._sender_input)

        self._prefix_input = QLineEdit()
        self._prefix_input.setPlaceholderText("例如 /task")
        mf.addRow("主题前缀:", self._prefix_input)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(2, 120)
        self._interval_spin.setSuffix(" 秒")
        self._interval_spin.setValue(5)
        mf.addRow("轮询间隔:", self._interval_spin)

        self._imap_server_input = QLineEdit()
        self._imap_server_input.setPlaceholderText("例如 imap.qq.com")
        mf.addRow("IMAP 服务器:", self._imap_server_input)

        self._imap_port_spin = QSpinBox()
        self._imap_port_spin.setRange(1, 65535)
        self._imap_port_spin.setValue(993)
        mf.addRow("IMAP 端口:", self._imap_port_spin)

        self._imap_user_input = QLineEdit()
        self._imap_user_input.setPlaceholderText("完整的邮箱地址")
        mf.addRow("邮箱账号:", self._imap_user_input)

        self._imap_pwd_input = QLineEdit()
        self._imap_pwd_input.setPlaceholderText("QQ/163 邮箱请使用授权码")
        self._imap_pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        mf.addRow("IMAP 授权码:", self._imap_pwd_input)

        test_layout = QHBoxLayout()
        self._test_btn = QPushButton("测试连接")
        self._test_btn.clicked.connect(self._on_test_imap)
        test_layout.addStretch()
        test_layout.addWidget(self._test_btn)
        mf.addRow("", test_layout)

        self._test_status = QLabel("")
        self._test_status.setStyleSheet("color: gray;")
        mf.addRow("", self._test_status)

        layout.addWidget(mail_group)

        # --- SMTP 回复邮件配置 ---
        smtp_group = QGroupBox("SMTP 回复邮件（可选）")
        sf = QFormLayout(smtp_group)
        sf.setVerticalSpacing(8)

        smtp_hint = QLabel("启用后，OpenCode 的执行结果将通过邮件回复给发件人")
        smtp_hint.setStyleSheet("color: gray; font-size: 11px;")
        sf.addRow("", smtp_hint)

        self._smtp_server_input = QLineEdit()
        self._smtp_server_input.setPlaceholderText("例如 smtp.qq.com，留空则不回复邮件")
        sf.addRow("SMTP 服务器:", self._smtp_server_input)

        self._smtp_port_spin = QSpinBox()
        self._smtp_port_spin.setRange(1, 65535)
        self._smtp_port_spin.setValue(465)
        sf.addRow("SMTP 端口:", self._smtp_port_spin)

        self._smtp_user_input = QLineEdit()
        self._smtp_user_input.setPlaceholderText("留空则使用 IMAP 账号")
        sf.addRow("SMTP 账号:", self._smtp_user_input)

        self._smtp_pwd_input = QLineEdit()
        self._smtp_pwd_input.setPlaceholderText("留空则使用 IMAP 授权码")
        self._smtp_pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        sf.addRow("SMTP 授权码:", self._smtp_pwd_input)

        self._smtp_sender_input = QLineEdit()
        self._smtp_sender_input.setPlaceholderText("发件人地址，留空则使用邮箱账号")
        sf.addRow("发件人地址:", self._smtp_sender_input)

        smtp_test_layout = QHBoxLayout()
        self._smtp_test_btn = QPushButton("测试 SMTP")
        self._smtp_test_btn.clicked.connect(self._on_test_smtp)
        smtp_test_layout.addStretch()
        smtp_test_layout.addWidget(self._smtp_test_btn)
        sf.addRow("", smtp_test_layout)

        self._smtp_test_status = QLabel("")
        self._smtp_test_status.setStyleSheet("color: gray;")
        sf.addRow("", self._smtp_test_status)

        layout.addWidget(smtp_group)

        # --- OpenWork/OpenCode connection ---
        ow_group = QGroupBox("OpenWork / OpenCode 连接")
        ow_layout = QVBoxLayout(ow_group)

        of = QFormLayout()
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("留空则自动通过 opencode CLI 发送")
        of.addRow("服务器 URL:", self._url_input)

        self._ws_input = QLineEdit()
        self._ws_input.setPlaceholderText("Workspace ID（可选）")
        of.addRow("Workspace ID:", self._ws_input)

        self._token_input = QLineEdit()
        self._token_input.setPlaceholderText("Bearer Token（可选）")
        self._token_input.setEchoMode(QLineEdit.EchoMode.Password)
        of.addRow("Token:", self._token_input)
        ow_layout.addLayout(of)

        detect_layout = QHBoxLayout()
        self._detect_btn = QPushButton("\U0001f50d 自动检测")
        self._detect_btn.clicked.connect(self._on_detect)
        detect_layout.addWidget(self._detect_btn)
        self._start_oc_btn = QPushButton("\u25b6 启动 OpenCode")
        self._start_oc_btn.clicked.connect(self._on_start_opencode)
        detect_layout.addWidget(self._start_oc_btn)
        ow_layout.addLayout(detect_layout)

        self._detect_status = QLabel("")
        self._detect_status.setStyleSheet("color: gray;")
        ow_layout.addWidget(self._detect_status)

        layout.addWidget(ow_group)

        # --- 通用设置 ---
        general_group = QGroupBox("通用设置")
        gl = QVBoxLayout(general_group)
        self._auto_start_check = QCheckBox("开机自动启动 OpenCodeBridge")
        gl.addWidget(self._auto_start_check)
        layout.addWidget(general_group)

        btn_layout = QHBoxLayout()
        self._save_btn = QPushButton("保存配置")
        self._save_btn.clicked.connect(self._on_save)
        btn_layout.addStretch()
        btn_layout.addWidget(self._save_btn)
        layout.addLayout(btn_layout)
        layout.addStretch()

    def load_config(self, config: AppConfig):
        self._config = config
        self._sender_input.setText(config.sender)
        self._prefix_input.setText(config.command_prefix)
        self._interval_spin.setValue(config.poll_interval)
        self._imap_server_input.setText(config.imap_server)
        self._imap_port_spin.setValue(config.imap_port)
        self._imap_user_input.setText(config.imap_username)
        self._imap_pwd_input.setText(config.imap_password)
        self._smtp_server_input.setText(config.smtp_server)
        self._smtp_port_spin.setValue(config.smtp_port)
        self._smtp_user_input.setText(config.smtp_username)
        self._smtp_pwd_input.setText(config.smtp_password)
        self._smtp_sender_input.setText(config.smtp_sender)
        self._url_input.setText(config.openwork_url)
        self._ws_input.setText(config.workspace_id)
        self._token_input.setText(config.token)
        self._auto_start_check.setChecked(config.auto_start)

    def get_config(self) -> AppConfig:
        return AppConfig(
            sender=self._sender_input.text().strip(),
            command_prefix=self._prefix_input.text().strip() or "/task",
            poll_interval=self._interval_spin.value(),
            imap_server=self._imap_server_input.text().strip(),
            imap_port=self._imap_port_spin.value(),
            imap_username=self._imap_user_input.text().strip(),
            imap_password=self._imap_pwd_input.text(),
            smtp_server=self._smtp_server_input.text().strip(),
            smtp_port=self._smtp_port_spin.value(),
            smtp_username=self._smtp_user_input.text().strip(),
            smtp_password=self._smtp_pwd_input.text(),
            smtp_sender=self._smtp_sender_input.text().strip(),
            openwork_url=self._url_input.text().strip(),
            workspace_id=self._ws_input.text().strip(),
            token=self._token_input.text().strip(),
            auto_start=self._auto_start_check.isChecked(),
        )

    def _on_test_smtp(self):
        cfg = self.get_config()
        server = cfg.smtp_server
        port = cfg.smtp_port
        user = cfg.smtp_username or cfg.imap_username
        pwd = cfg.smtp_password or cfg.imap_password
        if not server or not user or not pwd:
            self._smtp_test_status.setText("请先填写 SMTP 服务器、账号和密码")
            self._smtp_test_status.setStyleSheet("color: red;")
            return
        self._smtp_test_btn.setEnabled(False)
        self._smtp_test_status.setText("正在测试...")
        self._smtp_test_status.setStyleSheet("color: gray;")
        from threading import Thread
        Thread(target=self._do_test_smtp, args=(server, port, user, pwd), daemon=True).start()

    def _do_test_smtp(self, server, port, user, pwd):
        try:
            ok, msg = test_smtp_connection(server, port, user, pwd)
        except Exception as e:
            ok, msg = False, f"异常: {e}"
        self.smtp_test_result.emit(ok, msg)

    def _on_smtp_test_result(self, ok: bool, msg: str):
        self._smtp_test_btn.setEnabled(True)
        if ok:
            self._smtp_test_status.setText(f"\u2713 {msg}")
            self._smtp_test_status.setStyleSheet("color: green;")
        else:
            self._smtp_test_status.setText(f"\u2717 {msg}")
            self._smtp_test_status.setStyleSheet("color: red;")

    def _on_test_imap(self):
        cfg = self.get_config()
        server = cfg.imap_server
        port = cfg.imap_port
        user = cfg.imap_username
        pwd = cfg.imap_password
        if not server or not user or not pwd:
            self._test_status.setText("请先填写 IMAP 服务器、账号和密码")
            self._test_status.setStyleSheet("color: red;")
            return
        self._test_btn.setEnabled(False)
        self._test_status.setText("正在测试...")
        self._test_status.setStyleSheet("color: gray;")
        from threading import Thread
        Thread(target=self._do_test_imap, args=(server, port, user, pwd), daemon=True).start()

    def _do_test_imap(self, server, port, user, pwd):
        try:
            ok, msg = test_imap_connection(server, port, user, pwd)
        except Exception as e:
            ok, msg = False, f"异常: {e}"
        self.test_result.emit(ok, msg)

    def _on_test_result(self, ok: bool, msg: str):
        self._test_btn.setEnabled(True)
        if ok:
            self._test_status.setText(f"\u2713 {msg}")
            self._test_status.setStyleSheet("color: green;")
        else:
            self._test_status.setText(f"\u2717 {msg}")
            self._test_status.setStyleSheet("color: red;")

    def _on_save(self):
        cfg = self.get_config()
        save_config(cfg)
        self._config = cfg
        set_auto_start(cfg.auto_start)

    def _on_detect(self):
        self._detect_status.setText("正在检测中...")
        self._detect_btn.setEnabled(False)
        try:
            ow = scan_openwork_servers()
            oc = scan_opencode_servers()
            servers = ow + oc
            if not servers and opencode_installed():
                self._detect_status.setText("未检测到运行中的服务，但已安装 opencode CLI（将自动降级使用）")
            elif servers:
                urls = ", ".join(s["url"] for s in servers)
                self._detect_status.setText(f"检测到: {urls}")
            else:
                self._detect_status.setText("未检测到任何服务。可点击「启动 OpenCode」")
            dialog = ServerDetectDialog(self)
            dialog.set_servers(servers)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                url = dialog.selected_url()
                if url:
                    self._url_input.setText(url)
                    self._detect_status.setText(f"已选择: {url}")
        finally:
            self._detect_btn.setEnabled(True)

    def _on_start_opencode(self):
        ok, msg = start_opencode_server()
        self._detect_status.setText(msg)
