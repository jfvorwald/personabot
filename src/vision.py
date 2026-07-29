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

# Anthropic's limit is larger, but a 20MB screenshot costs real latency for no
# benefit - detail beyond this is lost to resizing anyway.
MAX_BYTES = 5 * 1024 * 1024


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


async def fetch(attachment, timeout: float = 20.0) -> dict | None:
    """Download an attachment and encode it as an image block, or return None.

    The block shape is the API's: a base64 source rather than a URL, because
    Discord's CDN links are signed and time-limited, and handing a third party
    a link that may have expired is a failure mode that only shows up later.
    """
    kind = media_type(attachment)
    if kind is None:
        return None
    if too_big(attachment):
        log.info(
            "Skipping %s: %d KB is over the limit",
            getattr(attachment, "filename", "?"),
            (getattr(attachment, "size", 0) or 0) // 1024,
        )
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

    if not data or len(data) > MAX_BYTES:
        return None
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


async def blocks_for(message, limit: int = 4) -> list[dict]:
    """Every image on a message, as API content blocks.

    Bounded because a Discord message can carry ten attachments and a reply
    does not improve for having seen all of them.
    """
    out = []
    for attachment in list(getattr(message, "attachments", []) or [])[:limit]:
        block = await fetch(attachment)
        if block:
            out.append(block)
    return out


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
