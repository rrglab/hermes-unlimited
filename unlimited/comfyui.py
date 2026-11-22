"""Optional ComfyUI HTTP adapter. No credentials or execution authority implied.

Point this client at a trusted ComfyUI deployment; never expose it directly to
untrusted user-supplied URLs or workflow payloads without upstream policy checks.
"""
import ipaddress
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

_ID = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class ComfyUIError(RuntimeError):
    """Transport, protocol or remote execution error."""


class ComfyUI:
    def __init__(self, base_url="http://127.0.0.1:8188", *, timeout=30, opener=None):
        url = urlsplit(base_url)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
            raise ValueError("ComfyUI base URL must be an HTTP(S) origin")
        # Network egress is not authorized by this optional adapter. Only an
        # explicit numeric loopback address is accepted; no DNS or metadata IP.
        try:
            host = ipaddress.ip_address(url.hostname)
        except ValueError as exc:
            raise ValueError("COMFYUI_LOOPBACK_ONLY") from exc
        if not host.is_loopback:
            raise ValueError("COMFYUI_LOOPBACK_ONLY")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._open = opener or build_opener(ProxyHandler({}), _NoRedirect()).open

    def _request(self, path, *, payload=None, binary=False):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.base_url + path, data=data,
                          headers={"Content-Type": "application/json"} if data is not None else {},
                          method="POST" if data is not None else "GET")
        try:
            with self._open(request, timeout=self.timeout) as response:
                content = response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ComfyUIError("ComfyUI request failed") from exc
        if binary:
            return content
        try:
            return json.loads(content)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ComfyUIError("Invalid ComfyUI JSON response") from exc

    def submit(self, workflow, *, client_id=None):
        """Submit a validated API-format workflow; returns remote prompt ID."""
        if not isinstance(workflow, dict) or not workflow:
            raise ValueError("workflow must be a nonempty API-format object")
        if client_id is not None and (not isinstance(client_id, str) or not _ID.fullmatch(client_id)):
            raise ValueError("invalid client_id")
        payload = {"prompt": workflow}
        if client_id:
            payload["client_id"] = client_id
        result = self._request("/prompt", payload=payload)
        if not isinstance(result, dict) or not isinstance(result.get("prompt_id"), str) or not result["prompt_id"]:
            raise ComfyUIError("ComfyUI did not acknowledge prompt")
        return result

    def history(self, prompt_id):
        if not isinstance(prompt_id, str) or not _ID.fullmatch(prompt_id):
            raise ValueError("invalid prompt_id")
        result = self._request("/history/" + prompt_id)
        if not isinstance(result, dict):
            raise ComfyUIError("Invalid ComfyUI history")
        return result.get(prompt_id)

    def result(self, prompt_id):
        """Return remote state and output descriptors; never infer completion from submission."""
        entry = self.history(prompt_id)
        if entry is None:
            return {"prompt_id": prompt_id, "state": "unknown", "outputs": {}}
        if not isinstance(entry, dict):
            raise ComfyUIError("Invalid ComfyUI history entry")
        status = entry.get("status", {})
        if not isinstance(status, dict):
            raise ComfyUIError("Invalid ComfyUI status")
        state = "completed" if status.get("completed") is True and status.get("status_str") == "success" else (
            "failed" if status.get("status_str") == "error" else "pending")
        return {"prompt_id": prompt_id, "state": state, "outputs": entry.get("outputs", {}) if state == "completed" else {}}

    def download(self, *, filename, subfolder="", folder_type="output"):
        """Download one artifact only after the caller authorizes its descriptor."""
        if not isinstance(filename, str) or not filename or any(c in filename for c in ("/", "\\", "\x00")) or filename in (".", ".."):
            raise ValueError("invalid filename")
        if not isinstance(subfolder, str) or ".." in subfolder.split("/") or "\\" in subfolder or "\x00" in subfolder:
            raise ValueError("invalid subfolder")
        if folder_type not in ("output", "temp"):
            raise ValueError("unsupported folder type")
        return self._request("/view?" + urlencode({"filename": filename, "subfolder": subfolder, "type": folder_type}), binary=True)
