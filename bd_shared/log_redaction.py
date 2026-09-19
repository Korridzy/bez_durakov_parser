"""Pure-stdlib redaction for structured log event dictionaries."""

import re
from typing import Any

MASK = "[REDACTED]"
OMITTED = "[OMITTED]"
MAX_DEPTH = 12

MASKED_KEYS = frozenset(
    {
        "authorization",
        "proxyauthorization",
        "cookie",
        "setcookie",
        "apikey",
        "xapikey",
        "token",
        "accesstoken",
        "refreshtoken",
        "secret",
        "clientsecret",
        "password",
        "passwd",
        "openaiapikey",
        "openrouterapikey",
        "opencodeapikey",
        "databaseurl",
        "dburl",
    }
)
DROPPED_KEYS = frozenset(
    {
        "message",
        "messages",
        "prompt",
        "prompts",
        "response",
        "content",
        "reasoning",
        "reasoningcontent",
        "rows",
        "result",
        "results",
        "queryresult",
        "data",
    }
)
SENSITIVE_QUERY_PARAMS = frozenset(
    {"apikey", "token", "accesstoken", "key", "signature", "sig", "secret", "password"}
)

_CREDENTIALS_PATTERN = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)[^/@\s]+@"
)
_QUERY_PARAM_PATTERN = re.compile(r"([?&])([^=&#\s]+)=([^&#\s]*)")


def normalize_key(key: str) -> str:
    """Return the case- and separator-insensitive form used by redaction lists."""
    return re.sub(r"[-_\s]", "", key.casefold())


def scrub_string(text: str) -> str:
    """Mask credentials and sensitive query-string values wherever they occur."""
    scrubbed = _CREDENTIALS_PATTERN.sub(r"\g<scheme>[REDACTED]@", text)

    def replace_query_param(match: re.Match[str]) -> str:
        separator, name = match.group(1, 2)
        if normalize_key(name) in SENSITIVE_QUERY_PARAMS:
            return f"{separator}{name}={MASK}"
        return match.group(0)

    return _QUERY_PARAM_PATTERN.sub(replace_query_param, scrubbed)


def redact_value(value: Any, depth: int, seen: set[int]) -> Any:
    """Copy and redact a value while bounding recursion and detecting active cycles."""
    if isinstance(value, str):
        return scrub_string(value)
    if not isinstance(value, (dict, list, tuple)):
        return value
    if depth >= MAX_DEPTH:
        return MASK

    identity = id(value)
    if identity in seen:
        return MASK

    seen.add(identity)
    try:
        if isinstance(value, dict):
            redacted = {}
            for key, item in value.items():
                normalized = normalize_key(key) if isinstance(key, str) else None
                if normalized == "event":
                    redacted[key] = redact_value(item, depth + 1, seen)
                elif normalized in DROPPED_KEYS:
                    redacted[key] = OMITTED
                elif normalized in MASKED_KEYS:
                    redacted[key] = MASK
                else:
                    redacted[key] = redact_value(item, depth + 1, seen)
            return redacted

        return [redact_value(item, depth + 1, seen) for item in value]
    finally:
        seen.remove(identity)


def redact_sensitive(logger: Any, method_name: str, event_dict: dict[Any, Any]) -> dict[Any, Any]:
    """Structlog-compatible processor that returns a redacted copy of an event dict."""
    del logger, method_name
    if not isinstance(event_dict, dict):
        raise TypeError("event_dict must be a dict")
    return redact_value(event_dict, 0, set())
