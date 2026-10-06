import logging

import pytest

from app.core.logging import RedactingFilter, redact


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("rtsp://admin:secret@10.0.0.5:554/s1", "rtsp://***:***@10.0.0.5:554/s1"),
        (
            "postgresql+psycopg://korgoz:pw@localhost/korgoz",
            "postgresql+psycopg://***:***@localhost/korgoz",
        ),
        ("connect to http://user@host/x now", "connect to http://***:***@host/x now"),
        ("rtsp://10.0.0.5/stream", "rtsp://10.0.0.5/stream"),
        ("no url here", "no url here"),
    ],
)
def test_redact(raw: str, expected: str) -> None:
    assert redact(raw) == expected


def test_filter_redacts_formatted_args() -> None:
    record = logging.LogRecord(
        "camera", logging.INFO, __file__, 1, "Connecting to %s", ("rtsp://a:b@cam/1",), None
    )
    assert RedactingFilter().filter(record)
    assert record.getMessage() == "Connecting to rtsp://***:***@cam/1"
