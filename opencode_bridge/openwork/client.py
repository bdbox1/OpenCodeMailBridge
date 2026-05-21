import os
import json
import base64
import subprocess
import shutil
import time
import logging
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# opencode CLI helpers
# ---------------------------------------------------------------------------

def find_opencode_cli() -> Optional[str]:
    return shutil.which("opencode")


def opencode_installed() -> bool:
    return bool(find_opencode_cli())


# ---------------------------------------------------------------------------
# OpenWork server scan (legacy)
# ---------------------------------------------------------------------------

def _check_port(host: str, port: int) -> Optional[dict]:
    url = f"http://{host}:{port}"
    try:
        resp = httpx.get(f"{url}/health", timeout=0.8)
        if resp.status_code == 200:
            data = resp.json() if resp.content else {}
            return {
                "url": url,
                "type": "openwork" if port not in (4096,) else "opencode",
                "version": data.get("version", ""),
            }
    except (httpx.RequestError, httpx.TimeoutException, ValueError):
        pass
    return None


def scan_openwork_servers(ports: list[int] = None) -> list[dict]:
    if ports is None:
        ports = [8787, 8788, 8789, 4096, 3000, 3005]
    hosts = ("127.0.0.1", "localhost")
    seen = set()
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_check_port, h, p): (h, p) for h in hosts for p in ports}
        for f in as_completed(futures):
            r = f.result()
            if r and r["url"] not in seen:
                seen.add(r["url"])
                results.append(r)
    return results


def openwork_installed() -> bool:
    return bool(shutil.which("openwork"))


def start_openwork(workspace: str) -> tuple[bool, str]:
    try:
        subprocess.Popen(
            ["openwork", "start", "--workspace", workspace, "--approval", "auto"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True, "OpenWork 启动中..."
    except FileNotFoundError:
        return False, "未找到 openwork 命令，请先安装: npm install -g openwork-orchestrator"
    except Exception as e:
        return False, f"启动 OpenWork 失败: {e}"


# ---------------------------------------------------------------------------
# opencode serve API client
# ---------------------------------------------------------------------------

def _opencode_auth_header() -> Optional[str]:
    """Build Basic auth header from environment variables."""
    user = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    password = os.environ.get("OPENCODE_SERVER_PASSWORD")
    if not password:
        return None
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def scan_opencode_servers() -> list[dict]:
    """Scan for running opencode serve instances."""
    results = []
    auth = _opencode_auth_header()
    if not auth:
        return results
    desktop_ports = [51138, 51139, 51140, 51141, 51142]
    for port in (4096, 4097, 4098, 4099) + tuple(desktop_ports):
        try:
            resp = httpx.get(
                f"http://127.0.0.1:{port}/health",
                headers={"Authorization": auth},
                timeout=0.8,
            )
            if resp.status_code < 500:
                results.append({"url": f"http://127.0.0.1:{port}", "type": "opencode_api", "version": ""})
        except httpx.RequestError:
            pass
    return results


def start_opencode_server(port: int = 4096) -> tuple[bool, str]:
    """Start opencode serve in background with required env vars."""
    cli = find_opencode_cli()
    if not cli:
        return False, "未找到 opencode 命令，请先安装: npm install -g @opencode-ai/cli"
    try:
        # Set env vars for THIS process too so health checks work
        if not os.environ.get("OPENCODE_SERVER_USERNAME"):
            os.environ["OPENCODE_SERVER_USERNAME"] = "opencode"
        if not os.environ.get("OPENCODE_SERVER_PASSWORD"):
            os.environ["OPENCODE_SERVER_PASSWORD"] = os.urandom(16).hex()
        if not os.environ.get("DEEPSEEK_API_KEY") and not os.environ.get("OPENCODE_API_KEY"):
            logger.info("使用 OpenCode Zen 免费模型 (opencode/deepseek-v4-flash-free)")
        subprocess.Popen(
            [cli, "serve", "--port", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for _ in range(15):
            time.sleep(0.5)
            auth = _opencode_auth_header()
            if not auth:
                continue
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/health", headers={"Authorization": auth}, timeout=1)
                if r.status_code < 500:
                    return True, f"openCode 服务器已启动 (端口 {port})"
            except httpx.RequestError:
                pass
        return False, "openCode 服务器启动超时"
    except Exception as e:
        return False, f"启动 openCode 服务器失败: {e}"


class OpencodeServerClient:
    """Client for the opencode serve HTTP API."""

    def __init__(self, base_url: str = "http://127.0.0.1:4096"):
        self.base_url = base_url.rstrip("/")
        self._auth = _opencode_auth_header()
        self._session_id: Optional[str] = None

    # ----- status ----------------------------------------------------------

    def is_authenticated(self) -> bool:
        return self._auth is not None

    def health(self) -> bool:
        if not self._auth:
            return False
        try:
            r = httpx.get(f"{self.base_url}/health", headers={"Authorization": self._auth}, timeout=3)
            return r.status_code < 500
        except httpx.RequestError:
            return False

    # ----- session management ----------------------------------------------

    def ensure_session(self) -> bool:
        if self._session_id:
            return True
        if not self._auth:
            return False
        try:
            r = httpx.post(
                f"{self.base_url}/session",
                headers={"Authorization": self._auth, "Content-Type": "application/json"},
                content=b"{}",
                timeout=10,
            )
            if r.status_code == 200:
                self._session_id = r.json().get("id")
                return self._session_id is not None
        except (httpx.RequestError, ValueError):
            pass
        return False

    def create_session(self) -> Optional[str]:
        """Force-create a new session and return its id."""
        self._session_id = None
        if self.ensure_session():
            return self._session_id
        return None

    # ----- send & receive --------------------------------------------------

    def _extract_assistant(self, data: dict) -> tuple[Optional[bool], Optional[str]]:
        """Try to extract assistant text from session data or a single message."""
        # Check if data itself is an assistant message
        info = data.get("info", {})
        if info.get("role") == "assistant":
            error = info.get("error")
            if error:
                return False, f"模型错误: {error.get('data', {}).get('message', error.get('name', '未知错误'))}"
            parts = data.get("parts", [])
            texts = [p.get("text", "") for p in parts if p.get("type") == "text" and p.get("text")]
            if texts:
                return True, "\n".join(texts)

        # Check session messages array
        messages = data.get("messages") or data.get("history", [])
        for msg in reversed(messages):
            parts = msg.get("parts", [])
            if not parts:
                continue
            info = msg.get("info", {})
            role = info.get("role", "")
            if role == "assistant":
                error = info.get("error")
                if error:
                    return False, f"模型错误: {error.get('data', {}).get('message', error.get('name', '未知错误'))}"
                texts = [p.get("text", "") for p in parts if p.get("type") == "text" and p.get("text")]
                if texts:
                    return True, "\n".join(texts)
        return None, None

    def send_prompt(self, text: str) -> tuple[bool, str]:
        """Send a prompt and wait for the assistant response."""
        if not self._auth:
            return False, "未设置 OPENCODE_SERVER_PASSWORD 环境变量"
        if not self.ensure_session():
            return False, "无法创建 openCode 会话"

        # Prepend system instruction: AI should NOT send emails by itself,
        # just return text result — the app will auto-reply via SMTP.
        # If the AI creates files, mention their full paths in backticks
        # so the app can attach them to the reply email.
        wrapped = (
            "# 系统指令\n"
            "这是一个自动化邮件命令处理系统。用户通过邮件发送命令给你，执行结果会自动通过 SMTP 回复给发件人。"
            "你**不要**自行编写或调用任何代码发送邮件，只需返回执行结果文本即可。"
            "如果有生成文件（如截图、文档等），请在回复中用反引号标出文件的完整路径"
            "（例如 `C:\\Users\\...\\file.txt`），系统会自动将其作为附件发送。"
            f"\n\n用户命令:\n{text}"
        )

        body = json.dumps({
            "message": wrapped,
            "parts": [{"type": "text", "text": wrapped}],
        })

        # Quick POST attempt — if model is fast, we get response immediately
        try:
            with httpx.Client(timeout=10) as http:
                resp = http.post(
                    f"{self.base_url}/session/{self._session_id}/message",
                    headers={"Authorization": self._auth, "Content-Type": "application/json"},
                    content=body,
                )
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        ok, result = self._extract_assistant(data)
                        if ok is not None and result:
                            return ok, result
                    except (ValueError, json.JSONDecodeError):
                        pass
        except (httpx.TimeoutException, httpx.RequestError):
            logger.info("openCode POST 超时，转入轮询模式")

        return self._poll_response(timeout_sec=600)

    def _poll_response(self, timeout_sec: int = 300) -> tuple[bool, str]:
        cli = find_opencode_cli()
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            time.sleep(3)
            try:
                if cli:
                    result = subprocess.run(
                        [cli, "export", self._session_id],
                        capture_output=True, timeout=30,
                    )
                    if result.returncode != 0:
                        continue
                    stdout = result.stdout.decode("utf-8", errors="replace")
                    data = json.loads(stdout)
                else:
                    r = httpx.get(
                        f"{self.base_url}/session/{self._session_id}",
                        headers={"Authorization": self._auth},
                        timeout=10,
                    )
                    if r.status_code != 200:
                        continue
                    data = r.json()

                ok, result = self._extract_assistant(data)
                if ok is not None:
                    return ok, result if result else "已处理完成"

            except (json.JSONDecodeError, subprocess.TimeoutExpired):
                continue
            except Exception as e:
                logger.debug("轮询异常: %s", e)
                continue

        return True, f"消息已发送，但在 {timeout_sec} 秒内未获取到完整响应"

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Legacy OpenWorkClient (kept for backward compatibility, now delegates to
# OpencodeServerClient when possible)
# ---------------------------------------------------------------------------

class OpenWorkClient:
    def __init__(self, base_url: str = "", token: str = "", workspace_id: str = ""):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.token = token
        self.workspace_id = workspace_id
        self._client = httpx.Client(timeout=30.0)
        self._oc = OpencodeServerClient()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def health_check(self) -> bool:
        if not self.base_url:
            return False
        try:
            resp = self._client.get(f"{self.base_url}/health", timeout=5.0)
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    def detect_local(self) -> list[dict]:
        servers = scan_openwork_servers()
        if not servers:
            oc_servers = scan_opencode_servers()
            servers.extend(oc_servers)
        if not servers:
            if opencode_installed():
                servers.append({"url": "", "type": "opencode_cli", "version": ""})
        return servers

    def send_prompt(self, text: str) -> tuple[bool, str]:
        # 1) Try OpenWork inbox API
        if self.base_url and self.base_url.startswith("http"):
            try:
                resp = self._client.post(
                    f"{self.base_url}/workspace/{self.workspace_id}/inbox",
                    headers={"Authorization": f"Bearer {self.token}"},
                    files={"file": ("prompt.txt", text.strip().encode("utf-8"), "text/plain")},
                )
                if resp.status_code in (200, 201, 204):
                    return True, "已发送到 OpenWork (inbox)"
            except httpx.RequestError:
                pass

        # 2) Try opencode serve API
        if self._oc.is_authenticated() and self._oc.health():
            ok, detail = self._oc.send_prompt(text)
            if ok:
                return True, detail
            return False, f"openCode API 失败: {detail}"

        # 3) Try to start server and retry
        ok, msg = start_opencode_server()
        if ok:
            time.sleep(2)
            if self._oc.is_authenticated() and self._oc.health():
                return self._oc.send_prompt(text)
            return True, "服务已启动，请稍后重试"
        return False, f"无法连接 OpenCode 服务: {msg}"

    def close(self):
        self._client.close()
