"""Value types shared by the camera module and the rest of the pipeline."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

import numpy as np
import numpy.typing as npt

# BGR image as returned by OpenCV: shape (height, width, 3), dtype uint8.
Image = npt.NDArray[np.uint8]


class CameraStatus(StrEnum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class SourceKind(StrEnum):
    USB = "usb"  # device index, e.g. "0" -> /dev/video0
    NETWORK = "network"  # rtsp://, http://, ...
    FILE = "file"  # local video file (development, demos, tests)


@dataclass(frozen=True)
class CameraConfig:
    camera_id: int
    name: str
    # May contain credentials: excluded from repr, log only via `redact()`.
    source: str = field(repr=False)
    max_fps: float | None = None
    loop_video: bool = True


@dataclass(frozen=True, slots=True)
class Frame:
    camera_id: int
    index: int  # sequential number of frames published by this camera's worker
    timestamp: datetime  # capture time, UTC
    image: Image = field(repr=False)
