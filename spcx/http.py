"""Shared HTTP with the manners each API expects.

The SEC requires a declaring User-Agent with contact details and rate-limits to
10 requests/second. Getting blocked mid-run would leave a half-written snapshot,
so every fetch is throttled per host, retried with backoff, and raises on final
failure rather than returning something a collector might mistake for data.
"""

from __future__ import annotations

import gzip
import os
import time
import urllib.error
import urllib.parse
import urllib.request

CONTACT = os.environ.get("SPCX_CONTACT", "spcx-console <set SPCX_CONTACT>")
UA = f"spcx-console/0.3 ({CONTACT})"
_last_call: dict[str, float] = {}


# Retrying a 4xx cannot succeed and, on at least one source here, is actively
# punished: CelesTrak began enforcing one-download-per-update in March 2026 and
# sends repeat callers to its firewall. A 403 meaning "you already have this"
# must be handled as a normal outcome, not hammered.
NO_RETRY_STATUS = {400, 401, 403, 404, 410, 422}


class HttpStatusError(RuntimeError):
    def __init__(self, status: int, url: str, body: str = ""):
        self.status, self.url, self.body = status, url, body
        super().__init__(f"HTTP {status} from {url}: {body[:200]}")


def get(url: str, *, headers: dict | None = None, throttle: float = 0.15,
        retries: int = 3, timeout: int = 30) -> bytes:
    host = urllib.parse.urlsplit(url).netloc
    gap = time.time() - _last_call.get(host, 0)
    if gap < throttle:
        time.sleep(throttle - gap)

    hdrs = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
    hdrs.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                _last_call[host] = time.time()
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode(errors="replace")
            except Exception:
                pass
            if exc.code in NO_RETRY_STATUS:
                raise HttpStatusError(exc.code, url, body) from None
            last = exc
            time.sleep(2 ** attempt)
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last}")
