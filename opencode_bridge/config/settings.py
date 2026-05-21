import json
import logging
import os
import sys
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger("Settings")

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.json")


@dataclass
class AppConfig:
    sender: str = ""                     # allowed sender email
    command_prefix: str = "/task"        # subject prefix
    poll_interval: int = 5               # seconds between polls
    imap_server: str = ""                # IMAP server hostname
    imap_port: int = 993                 # IMAP SSL port
    imap_username: str = ""              # email address
    imap_password: str = ""              # password / app password
    smtp_server: str = ""                # SMTP server hostname
    smtp_port: int = 465                 # SMTP SSL port
    smtp_username: str = ""              # SMTP login (defaults to imap_username)
    smtp_password: str = ""              # SMTP password (defaults to imap_password)
    smtp_sender: str = ""                # From address for reply emails
    openwork_url: str = "http://127.0.0.1:4096"
    workspace_id: str = ""
    token: str = ""
    auto_start: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        return cls(
            sender=data.get("sender", ""),
            command_prefix=data.get("command_prefix", "/task"),
            poll_interval=data.get("poll_interval", 5),
            imap_server=data.get("imap_server", ""),
            imap_port=data.get("imap_port", 993),
            imap_username=data.get("imap_username", ""),
            imap_password=data.get("imap_password", ""),
            smtp_server=data.get("smtp_server", ""),
            smtp_port=data.get("smtp_port", 465),
            smtp_username=data.get("smtp_username", ""),
            smtp_password=data.get("smtp_password", ""),
            smtp_sender=data.get("smtp_sender", ""),
            openwork_url=data.get("openwork_url", "http://127.0.0.1:4096"),
            workspace_id=data.get("workspace_id", ""),
            token=data.get("token", ""),
            auto_start=data.get("auto_start", False),
        )


def load_config() -> AppConfig:
    if not os.path.exists(CONFIG_FILE):
        return AppConfig()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AppConfig.from_dict(data)
    except (json.JSONDecodeError, IOError):
        return AppConfig()


def save_config(config: AppConfig) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)


def set_auto_start(enabled: bool) -> None:
    """Add or remove the auto-start registry entry for Windows."""
    app_name = "OpenCodeBridge"
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if enabled:
            exe = sys.executable
            script = os.path.abspath(
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "main.py")
            )
            value = f'"{exe}" "{script}"'
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, value)
            logger.info("开机自启已启用: %s", value)
        else:
            try:
                winreg.DeleteValue(key, app_name)
                logger.info("开机自启已禁用")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        logger.warning("设置开机自启失败: %s", e)
