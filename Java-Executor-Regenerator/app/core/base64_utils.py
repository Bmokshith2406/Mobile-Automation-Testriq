# app/core/base64_utils.py

import base64
import re


def normalize_base64(b64: str) -> bytes:
    """
    Strict image base64 decoder.

    - Removes data URL headers
    - Removes whitespace
    - Validates base64
    - Decodes to raw bytes
    - Verifies supported image signature
    """

    if not b64 or not isinstance(b64, str):
        raise ValueError("Empty or invalid base64 string")

    # Remove data URL prefix if present
    if b64.startswith("data:image"):
        b64 = re.sub(r"^data:image/.+;base64,", "", b64)

    # Remove whitespace/newlines
    b64 = "".join(b64.split())

    try:
        image_bytes = base64.b64decode(b64, validate=True)
    except Exception as exc:
        raise ValueError("Invalid base64 encoding") from exc

    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return image_bytes

    if image_bytes[:3] == b"\xff\xd8\xff":
        return image_bytes

    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return image_bytes

    raise ValueError("Decoded bytes are not a supported image")
