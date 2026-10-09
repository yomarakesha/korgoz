"""Add a camera directly to the database (no API login needed); reuse it if the name exists.

Usage:
    python -m scripts.add_camera --name Webcam --source 0
    python -m scripts.add_camera --name "Demo video" --source data/samples/vtest.avi

Prints only the camera id on stdout (used by scripts/windows/start.ps1). The source may
contain a password, so it is never printed or written to the audit log.
"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Camera
from app.database.session import get_session_factory
from app.security import audit
from app.security.types import AuditAction


def ensure_camera(db: Session, name: str, source: str) -> tuple[Camera, bool]:
    """The camera named `name` (first by id), created with `source` if missing. Commits."""
    camera = db.scalars(select(Camera).where(Camera.name == name).order_by(Camera.id)).first()
    if camera is not None:
        return camera, False
    camera = Camera(name=name, stream_url=source)
    db.add(camera)
    db.flush()
    audit.record(
        db,
        AuditAction.CAMERA_CREATED,
        user=None,
        username="(cli)",
        ip_address=None,
        target_type="camera",
        target_id=camera.id,
        details={"name": name, "source": "cli"},
    )
    db.commit()
    return camera, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True)
    parser.add_argument("--source", required=True, help="USB index, RTSP/HTTP URL or file path")
    args = parser.parse_args()
    with get_session_factory()() as db:
        camera, _ = ensure_camera(db, args.name, args.source)
    print(camera.id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
