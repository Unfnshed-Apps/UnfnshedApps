"""
Background connection health-check worker shared by all Unfnshed apps.

Re-evaluates the best server (localhost -> LAN -> remote) off the main thread.
"""

import requests as _requests
from PySide6.QtCore import Signal, QThread


class ConnectionWorker(QThread):
    """Re-evaluates the best server (localhost -> LAN -> remote) off the main thread.

    Emits finished(ok, best_url, conn_type) when done.
    """
    finished = Signal(bool, str, str)  # ok, best_url, conn_type

    def __init__(self, api):
        super().__init__()
        self._api = api

    def _check_health(self, url, timeout=3):
        try:
            resp = _requests.get(f"{url}/health", headers=self._api.headers, timeout=timeout)
            return resp.status_code == 200
        except Exception:
            return False

    def run(self):
        best_url = None
        conn_type = None

        if self._check_health(self._api.LOCAL_URL, timeout=2):
            best_url = self._api.LOCAL_URL
            conn_type = "local"
        elif self._api.lan_server_ip:
            lan_url = f"http://{self._api.lan_server_ip}:8000"
            if self._check_health(lan_url, timeout=3):
                best_url = lan_url
                conn_type = "lan"

        if not best_url:
            if self._check_health(self._api.REMOTE_URL, timeout=5):
                best_url = self._api.REMOTE_URL
                conn_type = "remote"

        self.finished.emit(best_url is not None, best_url or "", conn_type or "")
