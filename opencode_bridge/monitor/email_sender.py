import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.header import Header
from email import encoders
from threading import Thread
from typing import Optional

logger = logging.getLogger(__name__)


def test_smtp_connection(server: str, port: int, username: str, password: str) -> tuple[bool, str]:
    """Test SMTP connection with guaranteed timeout (15s)."""
    result: list[tuple[bool, str]] = []

    def _run():
        try:
            ctx = ssl.create_default_context()
            if port == 465:
                with smtplib.SMTP_SSL(server, port, context=ctx, timeout=10) as smtp:
                    smtp.login(username, password)
            else:
                with smtplib.SMTP(server, port, timeout=10) as smtp:
                    smtp.starttls(context=ctx)
                    smtp.login(username, password)
            result.append((True, "SMTP 连接成功"))
        except smtplib.SMTPAuthenticationError:
            result.append((False, "登录失败：账号或密码错误"))
        except smtplib.SMTPException as e:
            result.append((False, f"SMTP 错误: {e}"))
        except ConnectionRefusedError:
            result.append((False, "连接被拒绝，请检查服务器和端口"))
        except TimeoutError:
            result.append((False, "连接超时"))
        except OSError as e:
            result.append((False, f"网络错误: {e}"))
        except Exception as e:
            result.append((False, f"未知错误: {e}"))

    t = Thread(target=_run, daemon=True)
    t.start()
    t.join(15)
    if not result:
        return False, "连接超时（15秒）"
    return result[0]


def send_email(
    server: str, port: int, username: str, password: str,
    from_addr: str, to_addr: str, subject: str, body: str,
    attachments: Optional[list[str]] = None,
) -> tuple[bool, str]:
    """Send an email via SMTP with optional file attachments. Runs in current thread."""
    try:
        if attachments:
            msg = MIMEMultipart()
            msg.attach(MIMEText(body, "plain", "utf-8"))
            for fpath in attachments:
                if not os.path.isfile(fpath):
                    continue
                with open(fpath, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                fname = os.path.basename(fpath)
                part.add_header("Content-Disposition", "attachment", filename=Header(fname, "utf-8").encode())
                msg.attach(part)
        else:
            msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg["Subject"] = Header(subject, "utf-8")

        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(server, port, context=ctx, timeout=30) as smtp:
                smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(server, port, timeout=30) as smtp:
                smtp.starttls(context=ctx)
                smtp.login(username, password)
                smtp.send_message(msg)
        return True, f"邮件已发送至 {to_addr}"
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP 登录失败：账号或密码错误"
    except smtplib.SMTPException as e:
        return False, f"SMTP 发送失败: {e}"
    except Exception as e:
        return False, f"发送邮件异常: {e}"
