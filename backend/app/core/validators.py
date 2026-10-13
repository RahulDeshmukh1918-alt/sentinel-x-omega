"""Pure validation helpers (no framework imports) for sources, paths and uploads."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from backend.app.core.enums import SourceType

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class SourceValidationError(ValueError):
    pass


def mask_credentials(uri: str) -> str:
    """Hide user:password in URLs, e.g. rtsp://admin:pw@10.0.0.5/s1 -> rtsp://***@10.0.0.5/s1."""
    try:
        parts = urlsplit(uri)
    except ValueError:
        return "***"
    if parts.username or parts.password:
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, f"***@{host}", parts.path, "", ""))
    if parts.query:  # tokens are often passed as query parameters
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "***", ""))
    return uri


def safe_path_within(base_dir: Path, relative: str) -> Path:
    """Resolve ``relative`` inside ``base_dir`` and refuse anything that escapes it."""
    if not relative or "\x00" in relative:
        raise SourceValidationError("empty or invalid path")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise SourceValidationError("absolute paths are not allowed; use a path relative to the sample video folder")
    base = base_dir.resolve()
    resolved = (base / candidate).resolve()
    if resolved != base and base not in resolved.parents:
        raise SourceValidationError("path escapes the allowed video directory")
    return resolved


def validate_source(source_type: SourceType, uri: str, *, sample_dir: Path, allowed_ext: list[str]) -> str:
    """Validate a camera source definition. Returns the normalised URI."""
    uri = uri.strip()
    if source_type == SourceType.WEBCAM:
        if not uri.isdigit() or int(uri) > 16:
            raise SourceValidationError("WEBCAM source must be a device index between 0 and 16")
        return str(int(uri))
    if source_type == SourceType.RTSP:
        parts = urlsplit(uri)
        if parts.scheme.lower() not in {"rtsp", "rtsps", "http", "https"} or not parts.hostname:
            raise SourceValidationError("RTSP source must be an rtsp://, rtsps:// or http(s):// URL with a host")
        return uri
    if source_type == SourceType.FILE:
        path = safe_path_within(sample_dir, uri)
        if path.suffix.lower() not in allowed_ext:
            raise SourceValidationError(f"unsupported video extension {path.suffix!r}; allowed: {allowed_ext}")
        return uri.replace("\\", "/")
    raise SourceValidationError(f"unsupported source type {source_type}")


def sanitise_filename(name: str, max_len: int = 80) -> str:
    stem = Path(name or "upload").name  # drop any directory components
    cleaned = _SAFE_FILENAME.sub("_", stem).strip("._") or "upload"
    return cleaned[-max_len:]
