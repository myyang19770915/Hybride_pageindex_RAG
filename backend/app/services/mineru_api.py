import json
import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Result/image limits keep responses sane for the interactive playground.
_HEALTH_TIMEOUT = 60.0  # seconds to wait for the sidecar to answer /health


class MineruApiError(RuntimeError):
    """Raised when the MinerU FastAPI service is unavailable or returns an error."""


class MineruApiClient:
    """Manage and proxy to MinerU's own FastAPI service (``mineru-api``).

    A single sidecar process is launched lazily and reused, so parsing models stay
    warm across requests (the playground re-runs with different params often).
    Set ``MINERU_API_URL`` to use an externally managed service instead.
    """

    _process: subprocess.Popen | None = None
    _lock = threading.Lock()

    def base_url(self) -> str:
        settings = get_settings()
        if settings.mineru_api_url:
            return settings.mineru_api_url.rstrip("/")
        return f"http://127.0.0.1:{settings.mineru_api_port}"

    def _is_healthy(self, base_url: str) -> bool:
        try:
            response = httpx.get(f"{base_url}/health", timeout=3.0)
            return response.status_code == 200
        except Exception:
            return False

    def status(self) -> dict:
        base_url = self.base_url()
        return {
            "base_url": base_url,
            "managed": get_settings().mineru_api_url is None,
            "healthy": self._is_healthy(base_url),
        }

    @staticmethod
    def _listener_pid(port: int) -> str | None:
        """PID listening on 127.0.0.1:port (Windows netstat), else None."""
        if os.name != "nt":
            return None
        try:
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=10
            ).stdout
        except Exception:
            return None
        for line in out.splitlines():
            if f"127.0.0.1:{port}" in line and "LISTENING" in line.upper():
                return line.split()[-1]
        return None

    def reset_managed(self) -> None:
        """Kill an orphaned managed sidecar on our port so the next parse spawns a
        fresh one with the current environment (e.g. dated output root).

        Called on backend startup; no-op when using an external MINERU_API_URL or
        when autostart is disabled.
        """
        settings = get_settings()
        if settings.mineru_api_url or not settings.mineru_api_autostart:
            return
        pid = self._listener_pid(settings.mineru_api_port)
        if pid:
            try:
                subprocess.run(
                    ["taskkill", "/PID", pid, "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
                logger.info(
                    "Reset orphaned mineru-api sidecar (pid %s) on port %s",
                    pid,
                    settings.mineru_api_port,
                )
            except Exception:
                logger.warning("Failed to reset mineru-api sidecar on startup")
        MineruApiClient._process = None

    def ensure_started(self) -> str:
        """Return a healthy base URL, launching the local sidecar if needed."""
        base_url = self.base_url()
        settings = get_settings()

        if self._is_healthy(base_url):
            return base_url
        if settings.mineru_api_url:
            raise MineruApiError(f"External mineru-api at {base_url} is not reachable.")
        if not settings.mineru_api_autostart:
            raise MineruApiError("mineru-api is not running and autostart is disabled.")

        with self._lock:
            if self._is_healthy(base_url):
                return base_url
            self._spawn(settings.mineru_api_port)
            deadline = time.monotonic() + _HEALTH_TIMEOUT
            while time.monotonic() < deadline:
                if self._is_healthy(base_url):
                    return base_url
                if self._process and self._process.poll() is not None:
                    raise MineruApiError(
                        "mineru-api exited during startup; check logs/mineru_api.log."
                    )
                time.sleep(1.0)
            raise MineruApiError("mineru-api did not become healthy in time.")

    def _spawn(self, port: int) -> None:
        if self._process and self._process.poll() is None:
            return
        command = shutil.which("mineru-api")
        if not command:
            raise MineruApiError("mineru-api executable not found in PATH.")
        # Date-partition playground output: output/mineru-api/YYYY-MM-DD/<task_id>/...
        date_seg = datetime.now().strftime("%Y-%m-%d")
        output_root = os.path.join("output", "mineru-api", date_seg)
        os.makedirs(output_root, exist_ok=True)
        env = {
            **os.environ,
            "MINERU_API_DISABLE_ACCESS_LOG": "1",
            "MINERU_API_OUTPUT_ROOT": os.path.abspath(output_root),
        }
        log_path = os.path.join("logs", "mineru_api.log")
        os.makedirs("logs", exist_ok=True)
        logger.info("Launching mineru-api sidecar on port %s", port)
        MineruApiClient._process = subprocess.Popen(  # noqa: S603 - trusted local binary
            [command, "--host", "127.0.0.1", "--port", str(port)],
            stdout=open(log_path, "ab"),  # noqa: SIM115 - handed to the child process
            stderr=subprocess.STDOUT,
            env=env,
        )

    def parse(self, file_bytes: bytes, filename: str, params: dict) -> dict:
        """Proxy one file to mineru-api ``/file_parse`` and tidy the response."""
        base_url = self.ensure_started()

        def fmt(value: object) -> str:
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)

        data = {
            "return_md": "true",
            "return_content_list": "true",
            "return_images": "true",
            **{key: fmt(value) for key, value in params.items() if value is not None},
        }
        try:
            response = httpx.post(
                f"{base_url}/file_parse",
                files={"files": (filename, file_bytes, "application/pdf")},
                data=data,
                timeout=get_settings().mineru_timeout_seconds,
            )
        except Exception as exc:  # network / timeout
            raise MineruApiError(f"mineru-api request failed: {exc}") from exc

        if response.status_code != 200:
            detail = response.text[:500]
            raise MineruApiError(f"mineru-api returned {response.status_code}: {detail}")

        return self._tidy(response.json())

    @staticmethod
    def _tidy(payload: dict) -> dict:
        results = payload.get("results") or {}
        first = next(iter(results.values()), {}) if isinstance(results, dict) else {}
        content_list_raw = first.get("content_list")
        content_list = []
        if isinstance(content_list_raw, str) and content_list_raw.strip():
            try:
                content_list = json.loads(content_list_raw)
            except json.JSONDecodeError:
                content_list = []
        elif isinstance(content_list_raw, list):
            content_list = content_list_raw
        images = first.get("images") or {}
        return {
            "backend": payload.get("backend"),
            "version": payload.get("version"),
            "markdown": first.get("md_content") or "",
            "content_list": content_list,
            "images": images,
        }
