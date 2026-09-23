"""JPEG snapshots for messages that already cleared the hit threshold.

Pixels stay out of the Jev state. Ingest does not store images.
"""

from __future__ import annotations

import base64
import logging
from io import BytesIO
from typing import Any

logger = logging.getLogger(__name__)

MAX_IMAGES = 4
LONG_EDGE = 960
MAX_JPEG_BYTES = 180 * 1024
_QUALITIES = (70, 55, 40, 28, 18)


def message_is_photo(message: Any) -> bool:
    """Photos and image files only. Video and other attachments are skipped."""
    if message is None:
        return False
    for skip in ("video", "video_note", "gif", "sticker", "voice", "audio"):
        if getattr(message, skip, None):
            return False
    if getattr(message, "photo", None):
        return True
    document = getattr(message, "document", None)
    mime = str(getattr(document, "mime_type", "") or "") if document is not None else ""
    if not mime:
        file = getattr(message, "file", None)
        mime = str(getattr(file, "mime_type", "") or "") if file is not None else ""
    return mime.startswith("image/")


def compress_jpeg(raw: bytes) -> bytes | None:
    """Resize the long edge to about 960px and keep the JPEG bytes under 180KB."""
    if not raw:
        return None
    try:
        from PIL import Image, ImageOps
    except ImportError:
        logger.warning("Pillow is not installed; dropping hit image")
        return None
    try:
        with Image.open(BytesIO(raw)) as image:
            framed = ImageOps.exif_transpose(image)
            framed = framed.convert("RGB")
            framed.thumbnail((LONG_EDGE, LONG_EDGE), Image.Resampling.LANCZOS)
            for quality in _QUALITIES:
                buffer = BytesIO()
                framed.save(buffer, format="JPEG", quality=quality, optimize=True)
                data = buffer.getvalue()
                if len(data) <= MAX_JPEG_BYTES:
                    return data
    except Exception:
        logger.warning("Could not compress hit image", exc_info=True)
        return None
    return None


def encode_jpeg(raw: bytes) -> dict[str, str] | None:
    jpeg = compress_jpeg(raw)
    if not jpeg:
        return None
    return {"mime": "image/jpeg", "base64": base64.b64encode(jpeg).decode("ascii")}
