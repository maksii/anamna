"""Bounded Telegram Bot API transport. URLs and upstream errors never leave here."""
from __future__ import annotations

import json
import mimetypes
import re
import secrets
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import USER_AGENT

MAX_FILE_BYTES = 20 * 1024 * 1024
ERR_CONNECTION = "telegram.error_connection"
ERR_SIZE = "telegram.error_size"


class TelegramError(Exception):
    def __init__(self, key=ERR_CONNECTION, *, retry_after=0, permanent=False):
        super().__init__(key)
        self.key, self.retry_after, self.permanent = key, retry_after, permanent


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TelegramError(ERR_CONNECTION, permanent=True)


class TelegramAPI:
    def __init__(self, token: str):
        if not re.fullmatch(r"\d{5,20}:[\w-]{20,100}", token, re.ASCII):
            raise TelegramError("telegram.error_credentials", permanent=True)
        self._base = "https://api.telegram.org/bot" + token
        self._files = "https://api.telegram.org/file/bot" + token + "/"
        self._opener = build_opener(_NoRedirect())

    @staticmethod
    def _multipart(payload: dict, document: Path) -> tuple[bytes, str]:
        if document.stat().st_size > MAX_FILE_BYTES:
            raise TelegramError(ERR_SIZE, permanent=True)
        boundary = secrets.token_hex(24)
        parts = []
        for key, value in payload.items():
            form_value = json.dumps(value) if isinstance(value, (bool, dict, list)) else str(value)
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{form_value}\r\n'.encode())
        # ASCII filename avoids both header injection and platform encoding surprises.
        name = "document" + document.suffix.lower()
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
        parts.extend([document.read_bytes(), f"\r\n--{boundary}--\r\n".encode()])
        return b"".join(parts), "multipart/form-data; boundary=" + boundary

    def call(self, method: str, payload: dict | None = None, *, document: Path | None = None):
        if not re.fullmatch(r"[A-Za-z]+", method):
            raise TelegramError(permanent=True)
        payload = payload or {}
        content_type = "application/json"
        body = json.dumps(payload).encode()
        if document is not None:
            body, content_type = self._multipart(payload, document)
        request = Request(self._base + "/" + method, data=body, headers={"Content-Type": content_type, "User-Agent": USER_AGENT})
        try:
            with self._opener.open(request, timeout=35) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise TelegramError()
            parsed = json.loads(raw)
            if not parsed.get("ok"):
                self._error(parsed, method)
            return parsed.get("result")
        except HTTPError as error:
            try:
                parsed = json.loads(error.read(8192))
            except (ValueError, OSError):
                parsed = {"error_code": error.code}
            self._error(parsed, method)
        except (URLError, TimeoutError, OSError, ValueError):
            raise TelegramError() from None

    @staticmethod
    def _error(parsed, method=""):
        code = parsed.get("error_code", 500)
        if code == 400 and method == "editMessageText" and "message is not modified" in str(parsed.get("description", "")).casefold():
            return
        if code == 429:
            raise TelegramError("telegram.error_rate", retry_after=max(1, min(int(parsed.get("parameters", {}).get("retry_after", 30)), 86400))) from None
        if code == 409:
            raise TelegramError("telegram.error_conflict", permanent=True) from None
        raise TelegramError("telegram.error_credentials" if code == 401 else ERR_CONNECTION, permanent=400 <= code < 500) from None

    def download(self, file_id: str) -> bytes:
        result = self.call("getFile", {"file_id": file_id})
        path = str(result.get("file_path", ""))
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", path) or ".." in path.split("/") or path.startswith("/"):
            raise TelegramError("telegram.error_file", permanent=True)
        if int(result.get("file_size", 0)) > MAX_FILE_BYTES:
            raise TelegramError(ERR_SIZE, permanent=True)
        try:
            with self._opener.open(Request(self._files + path, headers={"User-Agent": USER_AGENT}), timeout=35) as response:
                data = response.read(MAX_FILE_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError):
            raise TelegramError("telegram.error_file") from None
        if not data or len(data) > MAX_FILE_BYTES:
            raise TelegramError(ERR_SIZE, permanent=True)
        return data
