from __future__ import annotations

import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from io import BytesIO

import requests
from defusedxml import ElementTree

from .core import APIHTTPError, CollectorError, CredentialError, DailyLimit, IntegrityError

BASE = "https://opendart.fss.or.kr/api/"


class DartClient:
    def __init__(self, api_key: str, *, interval=1.0, retries=2, session=None, sleep=time.sleep, clock=time.monotonic):
        if not api_key:
            raise CredentialError("DART_API_KEY is not configured in this execution environment")
        self._key = api_key
        self.session = session or requests.Session()
        self.interval, self.retries = max(1.0, interval), min(max(retries, 0), 3)
        self.sleep, self.clock, self.last = sleep, clock, None
        self.requests_made = 0

    def _status(self, payload):
        if not isinstance(payload, dict) or "status" not in payload:
            raise IntegrityError("API response has no status")
        code = str(payload["status"])
        if code == "020":
            error = DailyLimit("OpenDART daily request limit; checkpoint saved, stop all requests")
            error.api_status = code
            raise error
        if code in ("010", "011", "012", "901"):
            error = CredentialError(f"OpenDART authentication/access rejected (status {code})")
            error.api_status = code
            raise error
        if code not in ("000", "013"):
            # Ignore server message: it could contain reflected credential parameters.
            raise CollectorError(f"OpenDART API error (status {code if len(code) == 3 and code.isdigit() else 'unknown'})")
        return code

    def _get(self, endpoint: str, parameters: dict, *, binary: bool):
        if endpoint not in ("corpCode.xml", "list.json", "document.xml"):
            raise ValueError("Unsupported API endpoint")
        for attempt in range(self.retries + 1):
            if self.last is not None:
                self.sleep(max(0, self.interval - (self.clock() - self.last)))
            self.last = self.clock()
            self.requests_made += 1
            try:
                response = self.session.get(BASE + endpoint, params={**parameters, "crtfc_key": self._key},
                                            timeout=(10, 60), stream=True, allow_redirects=False)
            except requests.RequestException:
                if attempt == self.retries:
                    raise CollectorError("API transport failed; check network/proxy/TLS policy") from None
                self.sleep(2 ** attempt)
                continue
            try:
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    if attempt == self.retries:
                        raise APIHTTPError(endpoint, response.status_code, exhausted=True)
                    retry = response.headers.get("Retry-After", "")
                    try:
                        seconds = float(retry)
                    except ValueError:
                        try:
                            seconds = (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()
                        except (ValueError, TypeError, OverflowError):
                            seconds = 2 ** attempt
                    if seconds > 30:
                        raise CollectorError("Server requests a long retry delay; stop and resume later")
                    self.sleep(max(0, seconds))
                    continue
                if response.status_code != 200:
                    raise APIHTTPError(endpoint, response.status_code)
                data, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 128 * 1024 * 1024:
                        raise IntegrityError("API response exceeds safety size limit")
                    data.append(chunk)
                body = b"".join(data)
                if not binary:
                    try:
                        import json
                        payload = json.loads(body)
                    except (ValueError, UnicodeDecodeError):
                        raise IntegrityError("API returned invalid JSON") from None
                    if isinstance(payload, dict) and payload.get("status") in ("800", "900") and attempt < self.retries:
                        self.sleep(2 ** attempt)
                        continue
                    self._status(payload)
                    return payload
                if not body.startswith(b"PK"):
                    try:
                        root = ElementTree.parse(BytesIO(body)).getroot()
                        self._status({"status": root.findtext("status")})
                    except CollectorError:
                        raise
                    except Exception:
                        raise IntegrityError("API response is neither a ZIP nor a valid error XML") from None
                    raise IntegrityError("API returned an XML response instead of a ZIP")
                return body
            except requests.RequestException:
                if attempt == self.retries:
                    raise CollectorError("API response transfer failed") from None
                self.sleep(2 ** attempt)
            finally:
                response.close()
        raise CollectorError("API retry budget exhausted")

    def list(self, **parameters):
        return self._get("list.json", parameters, binary=False)

    def corporations(self):
        return self._get("corpCode.xml", {}, binary=True)

    def document(self, receipt_no):
        return self._get("document.xml", {"rcept_no": receipt_no}, binary=True)
