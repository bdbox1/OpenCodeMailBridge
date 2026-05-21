from datetime import datetime
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
from PyQt6.QtGui import QColor


class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        layout.addWidget(self._log)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self._log.clear)
        btn_layout.addWidget(clear_btn)
        layout.addLayout(btn_layout)

    def info(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.append(f'<span style="color: #666;">[{ts}]</span> {message}')

    def success(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.append(f'<span style="color: #666;">[{ts}]</span> <span style="color: green;">✓</span> {message}')

    def warn(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.append(f'<span style="color: #666;">[{ts}]</span> <span style="color: orange;">⚠</span> {message}')

    def error(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.append(f'<span style="color: #666;">[{ts}]</span> <span style="color: red;">✗</span> {message}')
