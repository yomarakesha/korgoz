"""Camera ingestion: video sources, per-camera worker threads, frame buffers."""

import os

# FFmpeg prints raw stream URLs (which may include credentials) to stderr,
# bypassing our redacting logger. Silence native logs unless explicitly overridden.
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
