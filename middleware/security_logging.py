"""
Structured security event logging and anomaly detection.

Provides:
  - SecurityLogger: JSON-structured log entries for auth events, API errors,
    and suspicious activity.
  - AnomalyDetector: rolling-window counter that fires when too many 401/403
    or failed logins come from the same IP within a short period.
  - register_security_hooks(app): wires after_request logging into a Flask app.
"""

import json
import logging
import os
import time
from collections import defaultdict
from threading import Lock

# ─── Logger setup ─────────────────────────────────────────────────────────────

_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter('%(message)s'))

security_logger = logging.getLogger('vibe.security')
security_logger.setLevel(logging.INFO)
security_logger.addHandler(_handler)
security_logger.propagate = False  # don't double-print in Flask's root logger


def _emit(event_type: str, data: dict) -> None:
    """Write one JSON line to the security log."""
    entry = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'event': event_type,
        **data,
    }
    security_logger.info(json.dumps(entry, ensure_ascii=False))


# ─── Public API ───────────────────────────────────────────────────────────────

def log_auth_attempt(
    ip: str,
    username: str,
    success: bool,
    method: str = 'password',
    reason: str | None = None,
) -> None:
    """Call after every login / registration attempt."""
    data: dict = {
        'ip': ip,
        'username': username,
        'method': method,
        'success': success,
    }
    if reason:
        data['reason'] = reason
    _emit('auth_login_success' if success else 'auth_login_fail', data)

    if not success:
        _anomaly.record_fail(ip)


def log_logout(ip: str, user_id: int, username: str) -> None:
    _emit('auth_logout', {'ip': ip, 'user_id': user_id, 'username': username})


def log_register(ip: str, username: str, success: bool, reason: str | None = None) -> None:
    data: dict = {'ip': ip, 'username': username, 'success': success}
    if reason:
        data['reason'] = reason
    _emit('auth_register', data)


def log_oauth(ip: str, provider: str, email: str | None, success: bool) -> None:
    _emit('auth_oauth', {'ip': ip, 'provider': provider, 'email': email, 'success': success})


def log_api_error(method: str, path: str, status: int, ip: str, user_id: int | None = None) -> None:
    data: dict = {'method': method, 'path': path, 'status': status, 'ip': ip}
    if user_id is not None:
        data['user_id'] = user_id
    level = 'api_error_5xx' if status >= 500 else 'api_error_4xx'
    _emit(level, data)

    if status in (401, 403):
        _anomaly.record_auth_rejection(ip)


def log_suspicious(ip: str, event: str, detail: str) -> None:
    _emit('suspicious', {'ip': ip, 'event': event, 'detail': detail})


# ─── Anomaly detector ─────────────────────────────────────────────────────────

class _AnomalyDetector:
    """
    Rolling-window counters per IP.
    Fires a suspicious-activity log entry when thresholds are breached.

    Windows and thresholds are intentionally loose — this is a trip-wire for
    obvious brute-force / scanning, not a WAF.
    """

    # (count, window_seconds, label)
    _FAIL_THRESHOLD    = (10,  60,  'too_many_login_failures')
    _REJECT_THRESHOLD  = (20, 120,  'too_many_auth_rejections')
    _BURST_THRESHOLD   = (200, 10,  'request_burst')

    def __init__(self) -> None:
        self._lock      = Lock()
        # ip -> list[timestamp]
        self._fail_ts:   dict[str, list[float]] = defaultdict(list)
        self._reject_ts: dict[str, list[float]] = defaultdict(list)
        self._burst_ts:  dict[str, list[float]] = defaultdict(list)

    def _check(
        self,
        store: dict[str, list[float]],
        ip: str,
        threshold: int,
        window: int,
        label: str,
    ) -> None:
        now = time.monotonic()
        cutoff = now - window
        store[ip] = [t for t in store[ip] if t > cutoff]
        store[ip].append(now)
        if len(store[ip]) == threshold:
            log_suspicious(ip, label, f'{threshold} events in {window}s')

    def record_fail(self, ip: str) -> None:
        n, w, label = self._FAIL_THRESHOLD
        with self._lock:
            self._check(self._fail_ts, ip, n, w, label)

    def record_auth_rejection(self, ip: str) -> None:
        n, w, label = self._REJECT_THRESHOLD
        with self._lock:
            self._check(self._reject_ts, ip, n, w, label)

    def record_request(self, ip: str) -> None:
        n, w, label = self._BURST_THRESHOLD
        with self._lock:
            self._check(self._burst_ts, ip, n, w, label)


_anomaly = _AnomalyDetector()


# ─── Flask integration ────────────────────────────────────────────────────────

def register_security_hooks(app) -> None:  # noqa: ANN001
    """
    Attach after_request hooks to the Flask app.
    Call once after app is created, before first request.
    """
    from flask import request as flask_request
    from flask_login import current_user

    @app.after_request
    def _log_errors_and_anomalies(response):
        status = response.status_code
        ip = flask_request.remote_addr or 'unknown'
        path = flask_request.path

        # Log all 4xx and 5xx responses (skip static assets to reduce noise)
        if status >= 400 and not path.startswith('/static/'):
            uid = None
            try:
                if current_user and current_user.is_authenticated:
                    uid = current_user.id
            except Exception:
                pass
            log_api_error(flask_request.method, path, status, ip, uid)

        # Burst detection on every request
        _anomaly.record_request(ip)

        return response
