"""Finding a GIF, from Tenor, over plain REST.

`FUTURE.md` flagged this as the hardest of the link behaviours to do well, and
the reason still holds: **a bad GIF is far more conspicuous than no GIF.** A
reaction image that does not quite fit reads worse than saying nothing, because
everyone can see exactly what was aimed for and missed. So this searches with
terms the model chose deliberately rather than picking something adjacent, and
declines rather than settling.

Optional, like image generation. With no TENOR_KEY set the whole path is inert
and the bot behaves as it did before. Nothing here decides whether a GIF is a
good idea; it takes search terms and returns a URL.

Posting the URL is the whole delivery mechanism. Discord expands a Tenor link
into a playing GIF by itself, which is also how the humans in the channel do
it, so this produces the same artefact rather than an uploaded file that looks
subtly different from everyone else's.
"""

from __future__ import annotations

import logging
import random
import urllib.parse

import aiohttp

log = logging.getLogger("personabot.gifs")

ENDPOINT = "https://tenor.googleapis.com/v2/search"

# Asked for by name so the response carries the format actually wanted rather
# than every format Tenor holds.
MEDIA_FILTER = "gif,tinygif"

# Tenor ranks by relevance, so the top handful are the plausible ones and
# anything past that is a worse fit than saying nothing.
CANDIDATES = 8


def available(key: str) -> bool:
    return bool(key and key.strip())


def _pick(payload: dict) -> str | None:
    """A URL from the top of the results, chosen at random among them.

    Random among the best few rather than strictly first: the same search
    returning the same GIF every time is a tell, and Tenor's ordering is stable.
    """
    results = payload.get("results") or []
    urls = []
    for result in results:
        formats = result.get("media_formats") or {}
        for key in ("gif", "tinygif", "mediumgif"):
            url = (formats.get(key) or {}).get("url")
            if url:
                urls.append(url)
                break
    if not urls:
        return None
    return random.choice(urls[:CANDIDATES])


async def find(
    terms: str,
    *,
    key: str,
    content_filter: str = "medium",
    timeout: float = 10.0,
) -> str | None:
    """Search for a GIF, or return None if anything at all goes wrong.

    content_filter defaults to medium rather than off. The persona is crude by
    design, but Tenor's content is not the persona's - an unexpectedly graphic
    result is somebody else's material appearing under Jaq's name in a friend's
    server, which is a different problem from Jaq being rude.
    """
    if not available(key) or not terms.strip():
        return None

    params = {
        "key": key,
        "q": terms.strip()[:200],
        "client_key": "personabot",
        "limit": str(CANDIDATES * 2),
        "media_filter": MEDIA_FILTER,
        "contentfilter": content_filter,
        "country": "US",
        "locale": "en_US",
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    log.info("Searching Tenor for %r", terms.strip()[:120])

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    # Logged whole rather than sliced: a 403 for a bad key and a
                    # 429 for a spent quota need different fixes, and truncating
                    # the body once already cost an evening on the image path.
                    detail = " ".join((await response.text()).split())
                    log.error(
                        "Tenor returned HTTP %s: %s", response.status, detail[:1000]
                    )
                    return None
                payload = await response.json()
    except Exception:
        log.warning("Tenor search failed to complete", exc_info=True)
        return None

    found = _pick(payload)
    if found is None:
        log.info("Nothing usable came back for %r", terms.strip()[:80])
    else:
        log.info("Found a GIF: %s", found)
    return found
