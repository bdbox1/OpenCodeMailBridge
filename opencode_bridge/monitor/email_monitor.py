import logging
import imaplib
import time
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from threading import Thread, Event
from typing import Optional, Callable

logger = logging.getLogger(__name__)


def _decode_str(s: Optional[str]) -> str:
    if not s:
        return ""
    parts = decode_header(s)
    result = []
    for data, charset in parts:
        if isinstance(data, bytes):
            try:
                result.append(data.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                result.append(data.decode("utf-8", errors="replace"))
        else:
            result.append(data)
    return "".join(result).strip()


def _get_body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode("utf-8", errors="replace")
    return ""


def test_imap_connection(server: str, port: int, username: str, password: str) -> tuple[bool, str]:
    """Test IMAP connection with guaranteed timeout (15s)."""
    result: list[tuple[bool, str]] = []

    def _run():
        try:
            conn = imaplib.IMAP4_SSL(server, port)
            conn.login(username, password)
            conn.select("INBOX")
            conn.logout()
            result.append((True, "连接成功"))
        except imaplib.IMAP4.error as e:
            msg = str(e)
            if "LOGIN failed" in msg or "Invalid" in msg:
                result.append((False, "登录失败：账号或密码错误"))
            else:
                result.append((False, f"IMAP 错误: {msg}"))
        except ConnectionRefusedError:
            result.append((False, "连接被拒绝，请检查服务器和端口是否正确"))
        except OSError as e:
            result.append((False, f"网络错误: {e}"))
        except Exception as e:
            result.append((False, f"未知错误: {e}"))

    t = Thread(target=_run, daemon=True)
    t.start()
    t.join(15)
    if not result:
        return False, "连接超时（15秒），请检查服务器地址和网络"
    return result[0]


class EmailMonitor:
    def __init__(
        self,
        imap_server: str,
        imap_port: int = 993,
        username: str = "",
        password: str = "",
        sender: str = "",
        own_email: str = "",
        command_prefix: str = "/task",
        poll_interval: int = 5,
    ):
        self._imap_server = imap_server
        self._imap_port = imap_port
        self._username = username
        self._password = password
        self._sender_filter = sender
        self._own_email = own_email.lower() if own_email else ""
        self._command_prefix = command_prefix
        self._poll_interval = poll_interval
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._last_error_log: float = 0
        self.on_message: Optional[Callable] = None
        self.on_status: Optional[Callable] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.is_running:
            return False
        self._stop_event.clear()
        self._thread = Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        self._emit_status(f"邮件监控已启动: {self._imap_server}:{self._imap_port}")
        return True

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        self._emit_status("邮件监控已停止")

    def _emit_status(self, msg: str):
        if self.on_status:
            self.on_status(msg)

    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                self._check_mail()
            except Exception as e:
                logger.warning("邮件检查异常: %s", e)
            time.sleep(self._poll_interval)

    def _check_mail(self):
        if not self._imap_server or not self._username or not self._password:
            return
        try:
            conn = imaplib.IMAP4_SSL(self._imap_server, self._imap_port)
            conn.login(self._username, self._password)
            conn.select("INBOX")
            _, data = conn.uid("SEARCH", None, "UNSEEN")
            if not data or not data[0]:
                conn.logout()
                return
            all_uids = sorted(data[0].decode().split(), key=int)
            if not all_uids:
                conn.logout()
                return

            # Only process the newest unread email
            uid_str = all_uids[-1]
            _, msg_data = conn.uid("FETCH", uid_str, "(RFC822)")
            if msg_data and msg_data[0]:
                raw_email = msg_data[0][1]
                parsed_msg = message_from_bytes(raw_email)
                self._process_email(parsed_msg, conn, uid_str)
            conn.logout()
        except (imaplib.IMAP4.error, ConnectionRefusedError, OSError) as e:
            now = time.time()
            if now - self._last_error_log > 30:
                logger.warning("IMAP 连接失败: %s", e)
                self._last_error_log = now

    def _process_email(self, msg: Message, conn: imaplib.IMAP4_SSL, uid_str: str):
        from opencode_bridge.monitor.message_parser import ParsedMessage

        sender = _decode_str(msg.get("From", ""))
        subject = _decode_str(msg.get("Subject", ""))
        logger.info("收到新邮件 - 发件人: %s, 主题: %s", sender, subject[:80])

        # sender filter
        if self._sender_filter and self._sender_filter.lower() not in sender.lower():
            logger.info("跳过发件人（不匹配过滤条件）: %s (过滤值: %s)", sender, self._sender_filter)
            self._mark_seen(conn, uid_str)
            return

        command = ""

        # subject prefix
        stripped = subject.strip()
        if stripped.startswith(self._command_prefix):
            cmd = stripped[len(self._command_prefix):].strip()
            if cmd:
                command = cmd
                logger.info("从主题提取到命令: %s", command[:100])

        # body: try prefix match
        if not command:
            body = _get_body(msg)
            if body:
                lines = [l.strip() for l in body.strip().splitlines() if l.strip()]
                for i, line in enumerate(lines):
                    if line.startswith(self._command_prefix):
                        cmd = line[len(self._command_prefix):].strip()
                        if cmd:
                            command = cmd
                            logger.info("从正文提取到命令（同行）: %s", command[:100])
                            break
                        elif i + 1 < len(lines):
                            command = lines[i + 1]
                            logger.info("从正文提取到命令（下一行）: %s", command[:100])
                            break

        if not command:
            logger.info("邮件不含命令前缀，标记已读后跳过")
            self._mark_seen(conn, uid_str)
            return

        self._mark_seen(conn, uid_str)
        parsed = ParsedMessage(raw=subject, sender=sender, command=command, matched=True)
        if self.on_message:
            self.on_message(parsed)

    def _mark_seen(self, conn: imaplib.IMAP4_SSL, uid_str: str):
        try:
            conn.uid("STORE", uid_str, "+FLAGS", "(\\Seen)")
        except imaplib.IMAP4.error as e:
            logger.warning("标记已读失败: %s", e)
