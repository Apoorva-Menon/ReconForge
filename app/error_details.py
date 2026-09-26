"""Small, redacted diagnostics for provider and scheduler failures."""
import re


_SECRET_PATTERNS = (
    (re.compile(r"(?i)(api[_-]?key|access[_-]?token|authorization|password|secret)(\s*[:=]\s*|\s+)([^\s,;]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)Bearer\s+[^\s,;]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)(mongodb(?:\+srv)?://)[^/@\s]+:[^/@\s]+@"), r"\1[REDACTED]@"),
)


def error_details(exc: Exception) -> dict:
    """Return bounded error context without persisting likely credentials."""
    message = str(exc).strip()
    for pattern, replacement in _SECRET_PATTERNS:
        message = pattern.sub(replacement, message)
    details = {"type": type(exc).__name__, "message": message[:1200] or "(no message)"}
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        details["status_code"] = status
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        details["status_code"] = response_status
    return details
