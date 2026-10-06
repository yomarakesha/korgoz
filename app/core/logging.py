"""Unified logging setup.

Format: `timestamp | level | module | message`.
A redaction filter masks credentials embedded in URLs
(e.g. `rtsp://admin:secret@10.0.0.5/stream` -> `rtsp://***:***@10.0.0.5/stream`)
so that a careless `logger.info(url)` cannot leak camera or database passwords.
"""

import logging
import re
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s:@]+(?::[^/\s@]*)?@")


def redact(text: str) -> str:
    """Mask `user:password@` in every URL inside `text`."""
    return _URL_CREDENTIALS.sub(r"\g<scheme>***:***@", text)


class RedactingFilter(logging.Filter):
    """Rewrites the final log message with credentials masked."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger once; safe to call repeatedly."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Route uvicorn logs through the same handler/format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
