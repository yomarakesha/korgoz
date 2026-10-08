"""KörGöz — Intelligent Vision & Situational Analytics Platform."""

import os

# Decompression-bomb guard for uploaded photos: a tiny PNG can declare a huge image
# and make cv2.imdecode allocate gigabytes. OpenCV reads this limit once, so it must
# be set before cv2 is first used; the package root is imported before any app module.
# 40 Mpx is well above any camera frame (4K = 8.3 Mpx) or phone photo.
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(40_000_000))

__version__ = "0.1.0"
