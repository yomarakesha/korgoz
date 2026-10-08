"""Download AI models (and optional sample media) with SHA-256 verification.

Usage:
    python -m scripts.download_models            # models only
    python -m scripts.download_models --samples  # + sample video/image for tests

Run once while online; afterwards KörGöz works fully offline.
Licenses: YOLOX - Apache-2.0 (Megvii); YuNet - MIT, SFace - Apache-2.0 (OpenCV Model Zoo);
samples - OpenCV repository (Apache-2.0) and public-domain official US government
portraits from Wikimedia Commons, used only for local testing (tests/ai).
"""

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class Asset:
    url: str
    path: Path
    sha256: str


MODELS = [
    Asset(
        "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx",
        Path("models/yolox_s.onnx"),
        "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063",
    ),
    Asset(
        "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx",
        Path("models/yolox_tiny.onnx"),
        "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7",
    ),
    Asset(
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
        "face_detection_yunet_2023mar.onnx",
        Path("models/face_detection_yunet_2023mar.onnx"),
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    Asset(
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/"
        "face_recognition_sface_2021dec.onnx",
        Path("models/face_recognition_sface_2021dec.onnx"),
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
]

_COMMONS = "https://upload.wikimedia.org/wikipedia/commons/"

SAMPLES = [
    Asset(
        "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/vtest.avi",
        Path("data/samples/vtest.avi"),
        "45cddc9490be69345cbdab64ca583be65987e864ca408038e648db99e10516cf",
    ),
    Asset(
        "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg",
        Path("data/samples/lena.jpg"),
        "7de7ed51a1594fff247f4cae2301eceacf5313d6011e37b4a4c8733f7bb72c07",
    ),
    # Face recognition samples: two different photos of two people + one stranger.
    Asset(
        _COMMONS + "f/f4/Joe_Biden_official_portrait_2013.jpg",
        Path("data/samples/biden_1.jpg"),
        "ad176d4d368e0944c666bea12e6372347f27d1194837e6731766f878d254bdee",
    ),
    Asset(
        _COMMONS + "6/68/Joe_Biden_presidential_portrait.jpg",
        Path("data/samples/biden_2.jpg"),
        "563f24c3a1a7392bb7f96831ba0ee8e7d53755ac9c053e9eeb520530542cc051",
    ),
    Asset(
        _COMMONS + "3/30/Senator_Kamala_Harris_Official_Portrait.jpg",
        Path("data/samples/harris_1.jpg"),
        "0b6bd423e58a202bd3d9cc2c2e6bdc2b72db484aab81438296e4a07b679eae78",
    ),
    Asset(
        _COMMONS + "4/41/Kamala_Harris_Vice_Presidential_Portrait.jpg",
        Path("data/samples/harris_2.jpg"),
        "69218c08f5834e8befba25bec00d83d70d68309cf0c96acaa436c034708882e0",
    ),
    Asset(
        _COMMONS + "8/8d/President_Barack_Obama.jpg",
        Path("data/samples/obama_1.jpg"),
        "744dd848fbb0584229169e01c4944664957c62495fb9e8af514a088ebca43e19",
    ),
]

# Wikimedia rejects requests without a descriptive User-Agent.
HEADERS = {"User-Agent": "KorGoz-model-downloader/0.1 (https://github.com/yomarakesha/korgoz)"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(asset: Asset, retries: int = 5) -> bool:
    if asset.path.is_file() and sha256(asset.path) == asset.sha256:
        print(f"ok        {asset.path} (already present)")
        return True
    asset.path.parent.mkdir(parents=True, exist_ok=True)
    partial = asset.path.with_suffix(asset.path.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            with httpx.stream(
                "GET", asset.url, headers=HEADERS, follow_redirects=True, timeout=60
            ) as response:
                response.raise_for_status()
                with partial.open("wb") as file:
                    for chunk in response.iter_bytes():
                        file.write(chunk)
            break
        except httpx.HTTPError as exc:
            print(f"retry {attempt}/{retries} {asset.path.name}: {type(exc).__name__}")
    else:
        print(f"FAILED    {asset.path}")
        return False

    actual = sha256(partial)
    if actual != asset.sha256:
        partial.unlink()
        print(f"FAILED    {asset.path}: checksum mismatch ({actual})")
        return False
    partial.replace(asset.path)
    print(f"ok        {asset.path}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Download KörGöz models")
    parser.add_argument("--samples", action="store_true", help="also download sample media")
    args = parser.parse_args()
    assets = MODELS + (SAMPLES if args.samples else [])
    results = [fetch(asset) for asset in assets]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
