"""
Centralized input validation for all user-facing entry points.
Import and use these helpers in route handlers instead of ad-hoc checks.
"""

import re
from flask import abort

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_POST_BODY       = 5_000
MAX_COMMENT_BODY    = 1_000
MAX_MESSAGE_BODY    = 4_000
MAX_CAPTION         = 500
MAX_STORY_COMMENT   = 500
MAX_REASON          = 500
MAX_CHAT_NAME       = 100
MAX_COMMUNITY_TITLE = 150
MAX_EVENT_TITLE     = 200
MAX_EVENT_DESC      = 2_000
MAX_SEARCH_QUERY    = 200
MAX_PAGE            = 500
MAX_BASE64_BYTES    = 25 * 1024 * 1024   # 25 MB decoded
MAX_FILE_SIZE       = 50 * 1024 * 1024   # 50 MB

# ---------------------------------------------------------------------------
# Emoji whitelist (common reaction set; extend as needed)
# ---------------------------------------------------------------------------

ALLOWED_EMOJIS = {
    "❤️", "🔥", "😂", "😮", "😢", "😡", "👍", "👎", "🎉", "💯",
    "😍", "🤔", "😭", "🥰", "😱", "🤣", "👏", "💪", "🙏", "✨",
    "💔", "🤯", "😤", "🥺", "😎", "🤝", "💀", "😏", "🫡", "⭐",
    "💫", "🌟", "✅", "❌", "⚡", "🎊", "🏆", "🎯", "💡", "❓",
    "💬", "👀", "🫶", "🙌", "🤮", "🫠", "🤩", "🥳", "😬", "🤑",
    "❤", "♥",
}

# ---------------------------------------------------------------------------
# MIME-type allowlists
# ---------------------------------------------------------------------------

ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_VIDEO_MIME = {"video/mp4", "video/webm", "video/quicktime"}
ALLOWED_AUDIO_MIME = {
    "audio/mpeg", "audio/wav", "audio/ogg", "audio/mp4",
    "audio/aac", "audio/x-m4a", "audio/webm",
}
ALLOWED_DOC_MIME = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}
ALLOWED_ALL_MIME = (
    ALLOWED_IMAGE_MIME | ALLOWED_VIDEO_MIME | ALLOWED_AUDIO_MIME | ALLOWED_DOC_MIME
)

# Allowed media data-URI schemes for base64 uploads
ALLOWED_MEDIA_DATA_MIME = ALLOWED_IMAGE_MIME | ALLOWED_VIDEO_MIME

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def validate_emoji(emoji: str, allowed: set = None) -> str:
    """Return emoji if allowed, else abort(400)."""
    if allowed is None:
        allowed = ALLOWED_EMOJIS
    if not emoji or emoji not in allowed:
        abort(400, description="Недопустимый emoji реакции")
    return emoji


def clamp_page(page, max_page: int = MAX_PAGE) -> int:
    """Return page clamped to [1, max_page]."""
    try:
        page = int(page)
    except (TypeError, ValueError):
        return 1
    return max(1, min(page, max_page))


def clamp_int(value, min_val: int = 0, max_val: int = None, default: int = 0) -> int:
    """Parse and clamp an integer; return default on parse error."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    if max_val is not None:
        value = min(value, max_val)
    return max(value, min_val)


def clamp_float(value, min_val: float = 0.0, max_val: float = None, default: float = 0.0) -> float:
    """Parse and clamp a float; return default on parse error."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if max_val is not None:
        value = min(value, max_val)
    return max(value, min_val)


def validate_text(value: str, max_len: int, field: str = "Поле",
                  min_len: int = 0, required: bool = False) -> str:
    """
    Validate text length. Abort with 400 when constraints violated.
    Returns the stripped value.
    """
    value = (value or "").strip()
    if required and not value:
        abort(400, description=f"{field} обязательно для заполнения")
    if min_len and len(value) < min_len:
        abort(400, description=f"{field} должно содержать не менее {min_len} символов")
    if len(value) > max_len:
        abort(400, description=f"{field} не должно превышать {max_len} символов")
    return value


def validate_base64_media(header: str, data: str) -> str:
    """
    Validate a data-URI header (the part before the comma).
    Returns the MIME type string if valid, else aborts with 400.

    Expected format: `data:<mime>;base64`
    """
    if not header.startswith("data:"):
        abort(400, description="Неверный формат медиа-данных")
    # strip 'data:' prefix and optional ';base64'
    mime = header[5:].split(";")[0].strip().lower()
    if mime not in ALLOWED_MEDIA_DATA_MIME:
        abort(400, description=f"Недопустимый тип медиа: {mime}")
    # Guard against excessively large payloads (base64 overhead ~33%)
    if len(data) > MAX_BASE64_BYTES * 4 // 3 + 64:
        abort(413, description="Файл слишком большой")
    return mime


def validate_file_mime(file, allowed_mime: set = None) -> str:
    """
    Check the uploaded file's declared content_type against an allowlist.
    Returns the cleaned mime type string, or aborts with 400.
    """
    if allowed_mime is None:
        allowed_mime = ALLOWED_ALL_MIME
    content_type = (getattr(file, "content_type", None) or "").split(";")[0].strip().lower()
    if not content_type or content_type not in allowed_mime:
        abort(400, description=f"Недопустимый тип файла: {content_type or '(unknown)'}")
    return content_type


def validate_file_size(file, max_bytes: int = MAX_FILE_SIZE) -> None:
    """
    Seek to end to measure size, then seek back. Aborts with 413 if too large.
    """
    pos = file.tell()
    file.seek(0, 2)
    size = file.tell()
    file.seek(pos)
    if size > max_bytes:
        abort(413, description=f"Файл слишком большой (максимум {max_bytes // (1024*1024)} МБ)")


def validate_redirect_url(url: str) -> bool:
    """
    Return True if the URL is a safe same-origin redirect target.
    Uses the same logic as _is_safe_redirect in auth.py.
    """
    from flask import request
    from urllib.parse import urlparse, urljoin
    if not url:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, url))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


def validate_webhook_url(url: str) -> str:
    """
    Validate that a webhook URL is HTTPS and not an SSRF target.
    Aborts with 400 on failure, returns the url on success.
    """
    from flask import current_app
    if not url:
        return url
    if not url.startswith("https://"):
        abort(400, description="Webhook URL должен начинаться с https://")
    from urllib.parse import urlparse
    import socket
    import ipaddress
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        abort(400, description="Неверный webhook URL")
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            addr = info[4][0]
            ip = ipaddress.ip_address(addr)
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_multicast or ip.is_reserved
                    or str(ip) in ("169.254.169.254", "::1")):
                abort(400, description="Webhook URL указывает на внутренний адрес")
    except Exception:
        abort(400, description="Не удалось разрешить webhook URL")
    return url


def validate_bot_commands(raw: str) -> str:
    """
    Validate that bot_commands is a JSON array of {command, description} objects.
    Returns the raw string if valid, aborts with 400 otherwise.
    """
    import json
    try:
        commands = json.loads(raw)
    except (ValueError, TypeError):
        abort(400, description="Команды бота: неверный JSON")
    if not isinstance(commands, list):
        abort(400, description="Команды бота должны быть массивом")
    if len(commands) > 100:
        abort(400, description="Слишком много команд бота (максимум 100)")
    for item in commands:
        if not isinstance(item, dict):
            abort(400, description="Каждая команда должна быть объектом")
        command = item.get("command", "")
        description = item.get("description", "")
        if not isinstance(command, str) or not isinstance(description, str):
            abort(400, description="Поля command и description должны быть строками")
        if len(command) > 32:
            abort(400, description="Имя команды не должно превышать 32 символа")
        if len(description) > 256:
            abort(400, description="Описание команды не должно превышать 256 символов")
        extra_keys = set(item.keys()) - {"command", "description"}
        if extra_keys:
            abort(400, description=f"Недопустимые поля в команде: {extra_keys}")
    return raw
