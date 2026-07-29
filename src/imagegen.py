"""Pictures, from Google's image models over plain REST.

Optional on purpose. This repo is public and almost nobody cloning it will set
a Google key, so with JAQ_GEMINI_KEY absent the whole feature is inert and the
bot behaves exactly as it did before images existed. `available()` is the one
question the rest of the code asks.

Nothing here imports Discord or Anthropic, and nothing here decides anything.
It takes a finished prompt and returns bytes. Whether Jaq wants a picture at
all is a question for decide.py and bot.py.

Every failure returns None, deliberately and quietly. A model that refuses, a
quota that ran out, and a network that dropped are all the same event from the
channel's point of view: no picture, and nothing said about it. An apology for
a failed image is worse than no image, because it is a bot talking about its
own plumbing in front of everyone.

aiohttp rather than the google-genai SDK: discord.py already brings aiohttp, so
this costs no new dependency, and one POST does not need a client library.
"""

from __future__ import annotations

import asyncio
import base64
import logging

import aiohttp

log = logging.getLogger("personabot.imagegen")

ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# The model returns text alongside the picture whether it is asked to or not.
# Requesting both and ignoring the text is more reliable than demanding IMAGE
# alone, which not every model in this family accepts.
MODALITIES = ["TEXT", "IMAGE"]


def available(key: str) -> bool:
    """Is image generation configured at all?

    Checked before any work is done - there is no point rolling dice, spending
    prompt tokens on the affordance, or letting the model write a description
    for a picture that can never be made.
    """
    return bool(key and key.strip())


def _first_image(payload: dict) -> bytes | None:
    """Dig the image out of a generateContent response.

    A blocked prompt, a safety stop, or a model that answered in prose all come
    back shaped like a normal response with no image part in it, so this returns
    None for every one of them without needing to tell them apart.
    """
    for candidate in payload.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            blob = part.get("inlineData") or part.get("inline_data")
            if not blob:
                continue
            data = blob.get("data")
            if not data:
                continue
            try:
                decoded = base64.b64decode(data)
            except (ValueError, TypeError):
                log.warning("Image part was not valid base64")
                continue
            # b64decode drops characters outside the alphabet rather than
            # raising, so junk decodes to nothing at all. Uploading that is a
            # zero-byte attachment in the channel.
            if decoded:
                return decoded
            log.warning("Image part decoded to nothing")
    return None


async def generate(
    prompt: str,
    *,
    key: str,
    model: str,
    timeout: float = 60.0,
) -> bytes | None:
    """Render `prompt`, or return None if anything at all goes wrong."""
    if not available(key) or not prompt.strip():
        return None

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": MODALITIES},
    }
    url = ENDPOINT.format(model=model)

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.post(
                url,
                json=body,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            ) as response:
                if response.status != 200:
                    # Body first, status second: the status alone does not say
                    # whether this was a bad key, an exhausted quota, or a
                    # model name that no longer exists, and those need
                    # different fixes.
                    detail = (await response.text())[:300]
                    log.warning(
                        "Image request failed: HTTP %s %s", response.status, detail
                    )
                    return None
                payload = await response.json()
    except asyncio.TimeoutError:
        log.warning("Image request timed out after %.0fs", timeout)
        return None
    except aiohttp.ClientError:
        log.warning("Image request failed to complete", exc_info=True)
        return None

    image = _first_image(payload)
    if image is None:
        # Most often a content filter. Worth a line in the log so a run of them
        # is visible, but never worth a line in the channel.
        log.info("No image came back (filtered, or the model answered in prose)")
    return image
