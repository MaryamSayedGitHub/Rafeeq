"""OpenCV clean-up before any reader sees the photo: resize, measure blur, boost contrast."""
from __future__ import annotations


class NotAnImage(ValueError):
    pass


def clean(photo_bytes: bytes) -> tuple[bytes, float | None]:
    """Returns (cleaned JPEG bytes, sharpness). Sharpness is None if OpenCV is not installed,
    in which case the original bytes are passed through unchanged."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        if not photo_bytes:
            raise NotAnImage("empty upload")
        return photo_bytes, None

    img = cv2.imdecode(np.frombuffer(photo_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise NotAnImage("not an image")
    scale = 1600 / max(img.shape[:2])
    if scale < 1:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    _, buf = cv2.imencode(".jpg", gray, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return buf.tobytes(), sharpness
