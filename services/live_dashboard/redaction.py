"""Secret redaction for untrusted live-event payloads."""

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?key(?:[_-]?id)?|private[_-]?key|authorization|"
    r"cookie|credential|password|passwd|secret|token)",
    re.IGNORECASE,
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----.*?"
    r"-----END(?: [A-Z0-9]+)* PRIVATE KEY-----",
    re.DOTALL,
)
_URL_CREDENTIALS = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s]+@",
    re.IGNORECASE,
)
_AUTH_HEADER = re.compile(
    r"(?im)(?P<name>authorization|proxy-authorization|x-api-key)\s*:\s*[^\r\n]+"
)
_INLINE_SECRET = re.compile(
    r"(?i)(?P<label>\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|"
    r"passwd|secret|token|signature|sig)\b\s*[:=]\s*)"
    r'''(?:(?P<quoted>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(?P<value>[^&\s,;]+))''',
    re.DOTALL,
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_KNOWN_TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,})\b")
_HIGH_ENTROPY_CREDENTIAL = re.compile(
    r"(?<![A-Za-z0-9_+/=-])"
    r"(?=[A-Za-z0-9_+/=-]{32,}(?![A-Za-z0-9_+/=-]))"
    r"(?=[A-Za-z0-9_+/=-]*[a-z])"
    r"(?=[A-Za-z0-9_+/=-]*[A-Z])"
    r"(?=[A-Za-z0-9_+/=-]*[0-9])"
    r"[A-Za-z0-9_+/=-]{32,}"
)


def _redact_inline_secret(match: re.Match[str]) -> str:
    quoted = match.group("quoted") or ""
    quote = quoted[0] if quoted else ""
    return f"{match.group('label')}{quote}{REDACTED}{quote}"


def _redact_text(value: str) -> str:
    value = _PRIVATE_KEY_BLOCK.sub(REDACTED, value)
    value = _URL_CREDENTIALS.sub(r"\g<scheme>" + REDACTED + "@", value)
    value = _AUTH_HEADER.sub(r"\g<name>: " + REDACTED, value)
    value = _INLINE_SECRET.sub(_redact_inline_secret, value)
    value = _BEARER_TOKEN.sub("Bearer " + REDACTED, value)
    value = _KNOWN_TOKEN.sub(REDACTED, value)
    return _HIGH_ENTROPY_CREDENTIAL.sub(REDACTED, value)


def redact(value: Any) -> Any:
    """Return a recursively redacted copy of JSON-like data."""

    if isinstance(value, Mapping):
        return {
            key: REDACTED if _SENSITIVE_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value
