"""
Centralized abuse-protection middleware.

Covers:
  - Body-size enforcement (1 MB for API routes, 10 MB for upload routes)
  - Proof-of-Work challenge/verify for public forms
  - Webhook signature verification (GitHub, YooKassa, Stripe, Telegram)
  - Per-user API rate-limit decorator
"""

import hashlib
import hmac
import os
import secrets
import time
from functools import wraps

from flask import current_app, g, jsonify, request, session

# ─── Body-size limits ────────────────────────────────────────────────────────

# API calls should not exceed 1 MB; file uploads get 10 MB; everything else
# inherits the global MAX_CONTENT_LENGTH (set to 10 MB in app.py).
_API_MAX_BYTES    = 1  * 1024 * 1024   # 1 MB
_UPLOAD_MAX_BYTES = 10 * 1024 * 1024   # 10 MB

# URL prefix → byte limit  (matched as startswith, so order matters)
_SIZE_RULES: list[tuple[str, int]] = [
    ('/api/',           _API_MAX_BYTES),
    ('/bot',            _API_MAX_BYTES),
    ('/upload',         _UPLOAD_MAX_BYTES),
    ('/photo_editor',   _UPLOAD_MAX_BYTES),
    ('/video_editor',   _UPLOAD_MAX_BYTES),
    ('/photo_transform',_UPLOAD_MAX_BYTES),
    ('/create',         _UPLOAD_MAX_BYTES),
    ('/community/create', _UPLOAD_MAX_BYTES),
]


def enforce_body_size():
    """before_request hook — reject oversized bodies early."""
    content_length = request.content_length
    if content_length is None:
        return

    path = request.path
    for prefix, limit in _SIZE_RULES:
        if path.startswith(prefix):
            if content_length > limit:
                label = f'{limit // (1024 * 1024)} MB'
                return jsonify({'error': f'Request too large (max {label})'}), 413
            return  # matched a rule — don't fall through

    # Default global limit (set to 10 MB in app.py via MAX_CONTENT_LENGTH)


# ─── Proof-of-Work ───────────────────────────────────────────────────────────

# Difficulty: nonce such that SHA-256(challenge + nonce) starts with DIFFICULTY
# leading zero hex characters.  3 zeros ≈ 4096 iterations on average (fast in JS).
_POW_DIFFICULTY = int(os.environ.get('POW_DIFFICULTY', '3'))
_POW_TTL        = 600  # seconds — challenge expires after 10 minutes


def _pow_prefix() -> str:
    return '0' * _POW_DIFFICULTY


def generate_pow_challenge() -> str:
    """
    Create a fresh challenge, store it in the session, and return it.
    Call this in a GET handler for the register / contact form.
    """
    challenge = secrets.token_hex(16)
    session['pow_challenge']    = challenge
    session['pow_challenge_ts'] = time.time()
    return challenge


def verify_pow_solution(challenge: str, nonce: str) -> bool:
    """
    Return True if SHA-256(challenge + nonce) has the required leading zeros
    AND the challenge matches the one stored in session AND it hasn't expired.
    """
    stored    = session.get('pow_challenge')
    issued_at = session.get('pow_challenge_ts', 0)

    if not stored or stored != challenge:
        return False
    if time.time() - issued_at > _POW_TTL:
        return False

    digest = hashlib.sha256(f'{challenge}{nonce}'.encode()).hexdigest()
    if not digest.startswith(_pow_prefix()):
        return False

    # Consume — prevents replay
    session.pop('pow_challenge', None)
    session.pop('pow_challenge_ts', None)
    return True


# ─── Webhook signature decorators ────────────────────────────────────────────

def require_github_signature(fn):
    """Verify X-Hub-Signature-256 using GITHUB_WEBHOOK_SECRET."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        secret = os.environ.get('GITHUB_WEBHOOK_SECRET', '')
        if not secret:
            current_app.logger.error('GITHUB_WEBHOOK_SECRET not set — rejecting webhook (fail-closed)')
            return jsonify({'error': 'Webhook verification unavailable'}), 503
        sig_header = request.headers.get('X-Hub-Signature-256', '')
        if not sig_header:
            return 'missing signature', 403
        expected = 'sha256=' + hmac.new(secret.encode(), request.data, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig_header):
            return 'invalid signature', 403
        return fn(*args, **kwargs)
    return wrapper


def require_yookassa_signature(fn):
    """
    Verify ЮKassa webhook HMAC-SHA256.

    ЮKassa sends the signature in the header ``Webhook-Signature`` as
    ``t=<timestamp>,v1=<hex-digest>``.  The signed string is
    ``<timestamp>.<raw-body>``.

    Set YOOKASSA_WEBHOOK_SECRET in the environment.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        secret = os.environ.get('YOOKASSA_WEBHOOK_SECRET', '')
        if not secret:
            current_app.logger.error('YOOKASSA_WEBHOOK_SECRET not set — rejecting webhook (fail-closed)')
            return jsonify({'error': 'Webhook verification unavailable'}), 503

        header = request.headers.get('Webhook-Signature', '')
        parts  = dict(p.split('=', 1) for p in header.split(',') if '=' in p)
        ts     = parts.get('t', '')
        v1     = parts.get('v1', '')

        if not ts or not v1:
            return jsonify({'error': 'missing webhook signature'}), 403

        signed_payload = f'{ts}.{request.data.decode("utf-8", errors="replace")}'
        expected = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected, v1):
            return jsonify({'error': 'invalid webhook signature'}), 403

        return fn(*args, **kwargs)
    return wrapper


def require_stripe_signature(fn):
    """
    Verify Stripe webhook using ``Stripe-Signature`` header (v1 scheme).

    Set STRIPE_WEBHOOK_SECRET (whsec_...) in the environment.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        secret = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
        if not secret:
            current_app.logger.error('STRIPE_WEBHOOK_SECRET not set — rejecting webhook (fail-closed)')
            return jsonify({'error': 'Webhook verification unavailable'}), 503

        sig_header = request.headers.get('Stripe-Signature', '')
        parts = dict(p.split('=', 1) for p in sig_header.split(',') if '=' in p)
        ts    = parts.get('t', '')
        v1    = parts.get('v1', '')

        if not ts or not v1:
            return jsonify({'error': 'missing Stripe-Signature'}), 403

        signed_payload = f'{ts}.{request.data.decode("utf-8", errors="replace")}'
        expected = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected, v1):
            return jsonify({'error': 'invalid Stripe signature'}), 403

        return fn(*args, **kwargs)
    return wrapper


def require_telegram_signature(fn):
    """
    Verify Telegram webhook via ``X-Telegram-Bot-Api-Secret-Token`` header.

    Set TELEGRAM_WEBHOOK_SECRET in the environment (the value you pass to
    setWebhook as ``secret_token``).
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
        if not expected:
            current_app.logger.error('TELEGRAM_WEBHOOK_SECRET not set — rejecting webhook (fail-closed)')
            return jsonify({'error': 'Webhook verification unavailable'}), 503

        token = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
        if not hmac.compare_digest(expected, token):
            return jsonify({'error': 'invalid Telegram secret token'}), 403

        return fn(*args, **kwargs)
    return wrapper


# ─── Per-user API rate limiting ───────────────────────────────────────────────
# Uses Redis sliding-window (ZADD/ZREMRANGEBYSCORE) when REDIS_URL is set;
# falls back to an in-process counter with a startup warning so single-worker
# dev deployments still work. In production with multiple gunicorn workers,
# set REDIS_URL to get accurate per-user limits.

import threading

class _InMemoryCounter:
    """Thread-safe sliding-window counter (single-process only)."""

    def __init__(self):
        self._store: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        now    = time.time()
        cutoff = now - window_seconds
        with self._lock:
            hits = [t for t in self._store.get(key, []) if t > cutoff]
            if len(hits) >= limit:
                self._store[key] = hits
                return False
            hits.append(now)
            self._store[key] = hits
        return True


class _RedisCounter:
    """Sliding-window counter backed by Redis sorted sets."""

    def __init__(self, redis_client):
        self._r = redis_client

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        now    = time.time()
        cutoff = now - window_seconds
        pipe   = self._r.pipeline()
        pipe.zremrangebyscore(key, '-inf', cutoff)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds + 1)
        _, _, count, _ = pipe.execute()
        return count <= limit


def _build_counter():
    redis_url = os.environ.get('REDIS_URL', '')
    if redis_url:
        try:
            import redis as _redis_lib
            client = _redis_lib.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
            client.ping()
            return _RedisCounter(client)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                f"Redis rate-limiter unavailable ({exc}); falling back to in-memory counter — "
                "limits will not be shared across workers."
            )
    else:
        import logging
        logging.getLogger(__name__).warning(
            "REDIS_URL not set — rate limiting is in-memory and not shared across "
            "gunicorn workers. Set REDIS_URL for accurate multi-worker limits."
        )
    return _InMemoryCounter()


_counter = _build_counter()


def user_rate_limit(limit: int = 100, window: int = 60):
    """
    Decorator: max *limit* requests per *window* seconds per authenticated user
    (falls back to IP for unauthenticated requests).

    Usage::

        @app.route('/api/something')
        @login_required
        @user_rate_limit(100, 60)
        def my_endpoint():
            ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from flask_login import current_user
            if current_user.is_authenticated:
                key = f'user:{current_user.id}:{request.endpoint}'
            else:
                key = f'ip:{request.remote_addr}:{request.endpoint}'

            if not _counter.is_allowed(key, limit, window):
                return jsonify({'error': 'Too many requests', 'retry_after': window}), 429

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def api_rate_limit(fn):
    """Convenience shortcut: 100 req / 60 s per user."""
    return user_rate_limit(100, 60)(fn)


# ─── AI generation rate limiting ─────────────────────────────────────────────

_AI_DAILY_LIMITS = {
    'free': int(os.environ.get('AI_FREE_DAILY',  '5')),
    'pro':  int(os.environ.get('AI_PRO_DAILY',  '50')),
}


def ai_rate_limit(fn):
    """
    Decorator for AI-generation endpoints.

    Reads ``current_user.subscription_plan`` (``'free'`` or ``'pro'``).
    Falls back to ``'free'`` if the attribute doesn't exist.
    Counter resets at midnight UTC (daily window = seconds until next midnight).
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        from flask_login import current_user
        if not current_user.is_authenticated:
            return jsonify({'error': 'Login required'}), 401

        plan  = getattr(current_user, 'subscription_plan', 'free') or 'free'
        limit = _AI_DAILY_LIMITS.get(plan, _AI_DAILY_LIMITS['free'])

        # Daily window aligned to calendar day
        now         = time.time()
        midnight    = now - (now % 86400)
        window_secs = int(midnight + 86400 - now)

        key = f'ai:{current_user.id}'
        if not _counter.is_allowed(key, limit, window_secs):
            return jsonify({
                'error': f'Daily AI limit reached ({limit} for {plan} plan)',
                'upgrade': plan == 'free',
            }), 429

        return fn(*args, **kwargs)
    return wrapper
