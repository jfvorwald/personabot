"""Letting Jaq actually look at what people send him.

Until now he read `clean_content` and nothing else, so an attachment was
invisible: a picture with a caption arrived as the caption alone, and a picture
with no caption arrived as an empty message and was dropped before anything
looked at it. Someone sending a screenshot and asking "what do you make of
this" was talking to something that could not see it.

Deliberately small and failure-tolerant, like the rest of the edges here. Every
problem - a download that fails, a file too large, a format the API will not
take - returns nothing and the reply happens without the picture. A message
that arrives without its attachment is worse than no reply only if nobody
notices; a crash is worse than both.

Nothing here decides anything. It fetches bytes and encodes them.
"""

from __future__ import annotations

import base64
import logging

import aiohttp

log = logging.getLogger("personabot.vision")

# What the API accepts. Discord will happily hand over a .bmp or a .tiff, and
# sending one is a 400 rather than a degraded answer.
SUPPORTED = {
    "image/jpeg": ("jpg", "jpeg"),
    "image/png": ("png",),
    "image/gif": ("gif",),
    "image/webp": ("webp",),
}

# What the API will accept in one image block.
MAX_BYTES = 5 * 1024 * 1024

# Images are scaled to roughly this on the long edge before the model sees
# them, so anything larger is bytes spent on detail that is discarded in
# transit. Downscaling here is therefore free: the model sees the same picture
# either way, and a 16MB phone screenshot fits instead of being dropped.
MAX_EDGE = 1568


def media_type(attachment) -> str | None:
    """The API media type for an attachment, or None if it is not an image.

    Trusts the declared content type first and falls back to the extension,
    because Discord sometimes serves a bare `application/octet-stream` for a
    file that is plainly a png.
    """
    declared = (getattr(attachment, "content_type", "") or "").split(";")[0].strip()
    if declared in SUPPORTED:
        return declared
    name = (getattr(attachment, "filename", "") or "").lower()
    for kind, extensions in SUPPORTED.items():
        if any(name.endswith("." + ext) for ext in extensions):
            return kind
    return None


def too_big(attachment) -> bool:
    return (getattr(attachment, "size", 0) or 0) > MAX_BYTES


def shrink(data: bytes) -> tuple[bytes, str] | None:
    """Fit an image inside the API's limit, or None if it cannot be read.

    A 16MB screenshot used to be skipped outright, and the reply happened as
    though nothing had been attached - so the answer was about a picture
    nobody had seen. Downscaling costs nothing real: the API scales to roughly
    MAX_EDGE anyway, so those bytes were never going to reach the model.

    PNG first because this is usually a screenshot and text survives it
    better; JPEG only when PNG will not fit.
    """
    try:
        from PIL import Image
    except ImportError:
        log.warning("Pillow is not installed, so large images cannot be resized")
        return None

    import io

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        log.warning("Could not decode an attachment as an image", exc_info=True)
        return None

    if max(img.size) > MAX_EDGE:
        ratio = MAX_EDGE / max(img.size)
        img = img.resize(
            (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
            Image.LANCZOS,
        )

    buffer = io.BytesIO()
    try:
        img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB").save(
            buffer, format="PNG", optimize=True
        )
    except Exception:
        buffer = io.BytesIO()
    if 0 < buffer.tell() <= MAX_BYTES:
        return buffer.getvalue(), "image/png"

    # Still too big, or PNG failed. Step the quality down rather than give up.
    for quality in (85, 70, 55, 40):
        buffer = io.BytesIO()
        try:
            img.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
        except Exception:
            return None
        if buffer.tell() <= MAX_BYTES:
            return buffer.getvalue(), "image/jpeg"
    return None


async def fetch(attachment, timeout: float = 20.0) -> dict | None:
    """Download an attachment and encode it as an image block, or return None.

    The block shape is the API's: a base64 source rather than a URL, because
    Discord's CDN links are signed and time-limited, and handing a third party
    a link that may have expired is a failure mode that only shows up later.
    """
    kind = media_type(attachment)
    if kind is None:
        return None

    url = getattr(attachment, "url", "")
    if not url:
        return None
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    log.warning("Attachment fetch failed: HTTP %s", response.status)
                    return None
                data = await response.read()
    except Exception:
        log.warning("Could not download an attachment", exc_info=True)
        return None

    if not data:
        return None

    original = len(data)
    if original > MAX_BYTES or kind == "image/gif":
        shrunk = shrink(data)
        if shrunk is None:
            log.warning(
                "Could not fit %s (%d KB) into the limit",
                getattr(attachment, "filename", "?"),
                original // 1024,
            )
            return None
        data, kind = shrunk
        log.info(
            "Resized %s: %d KB -> %d KB",
            getattr(attachment, "filename", "?"),
            original // 1024,
            len(data) // 1024,
        )
    log.info(
        "Looking at %s (%s, %d KB)",
        getattr(attachment, "filename", "?"),
        kind,
        len(data) // 1024,
    )
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": kind,
            "data": base64.b64encode(data).decode(),
        },
    }


async def blocks_for(message, limit: int = 4) -> tuple[list[dict], list[str]]:
    """Every image on a message, plus the names of any that could not be read.

    Both halves matter. The second exists because the first silently returning
    fewer blocks than there were attachments is how the bot ended up answering
    a question about a 16MB screenshot it had never seen, without mentioning
    that it had not seen it. A gap the model is not told about is a gap the
    model will confidently talk over.

    Bounded because a Discord message can carry ten attachments and a reply
    does not improve for having seen all of them.
    """
    blocks, missed = [], []
    for attachment in list(getattr(message, "attachments", []) or [])[:limit]:
        block = await fetch(attachment)
        if block:
            blocks.append(block)
        else:
            missed.append(getattr(attachment, "filename", "a file"))
    return blocks, missed


def unreadable_note(missed: list[str]) -> str:
    """What to tell the model about attachments it is not getting.

    Phrased so it says so rather than guessing: an answer about a picture
    nobody looked at is worse than admitting the picture did not arrive.
    """
    if not missed:
        return ""
    return (
        "\n\n[SYSTEM: " + ", ".join(missed) + " could not be read - wrong format, "
        "too large, or the download failed. You cannot see it. Say so plainly "
        "and do not guess at what it showed.]"
    )


def describes_attachments(message) -> str:
    """A short note naming what was attached, for the text side of the prompt.

    The model sees the images themselves; this tells it what they were called,
    which is often the most informative part of a screenshot.
    """
    names = [
        getattr(a, "filename", "?")
        for a in (getattr(message, "attachments", []) or [])
    ]
    if not names:
        return ""
    return "[attached: " + ", ".join(names) + "]"
