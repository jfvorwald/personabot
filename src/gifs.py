"""GIFs from a pool you curate, with no API behind it.

This started as a Tenor client. Tenor's API stopped accepting new keys in
January 2026 and began returning errors on 30 June, so that version was dead
before it ever ran. Discord's own picker moved to Klipy, but that is a
client-side integration and exposes nothing a bot can call.

The replacement turns out to be better suited to the actual problem. The hard
part was never finding *a* GIF, it was that **a bad GIF is far more conspicuous
than no GIF** - a reaction that nearly fits reads worse than words, because
everyone can see what was aimed at and missed. Searching a public index is a
gamble on that every single time. A pool somebody curated is not: every entry
is one that already fits this channel, so the model is choosing between good
options rather than hoping.

The file is markdown, gitignored like `persona.md`, because a list of what a
particular group finds funny is exactly as personal as the persona is.

    # anything outside a list item is a comment and ignored

    - https://media.tenor.com/xxxx/shrug.gif | shrug, dont care, whatever
    - https://media.tenor.com/yyyy/facepalm.gif | facepalm, disbelief, idiot

Tags after the pipe are what the model picks by. Everything else on the line is
ignored, so notes to yourself are free.
"""

from __future__ import annotations

import logging
import os
import random
import re

from paths import at_root

log = logging.getLogger("personabot.gifs")

POOL_FILE = "gifs.md"

# A list item, a URL, then optionally tags after a pipe.
_ENTRY = re.compile(r"^\s*[-*]\s*(?P<url>https?://\S+)\s*(?:\|\s*(?P<tags>.*))?$")


class Gif:
    def __init__(self, url: str, tags: list[str]):
        self.url = url
        self.tags = tags

    def __repr__(self) -> str:
        return f"Gif({self.url!r}, {self.tags!r})"


def parse(text: str) -> list[Gif]:
    """Read the pool. Anything that is not a list item with a URL is ignored.

    Forgiving on purpose: this is a file a person maintains by pasting links
    into it, and a malformed line should cost that line rather than the pool.
    """
    found = []
    fenced = False
    for line in (text or "").splitlines():
        # A fenced block in this file is the worked example showing somebody
        # how to write an entry, so its three sample URLs are xxxxx, yyyyy and
        # zzzzz. Parsed as data they become a pool of dead links that looks
        # populated: `gifs.md` reported four entries for a month while being
        # nothing but its own instructions. Same rule as skipping readme.md in
        # personnel - documentation is addressed to the author, not the loader.
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = _ENTRY.match(line)
        if not match:
            continue
        raw = match.group("tags") or ""
        tags = [t.strip().lower() for t in raw.split(",") if t.strip()]
        found.append(Gif(match.group("url").strip(), tags))
    return found


def load() -> list[Gif]:
    """The pool, read fresh so adding a GIF needs no restart."""
    try:
        with open(at_root(POOL_FILE), encoding="utf-8") as f:
            return parse(f.read())
    except OSError:
        return []


def available() -> bool:
    return bool(load())


def catalogue(pool: list[Gif], limit: int = 60) -> str:
    """The menu shown to the model: numbered tags, never URLs.

    Numbers rather than links because a URL in the prompt is a URL the model
    can paste into a message directly, bypassing every budget and cooldown -
    and because tags are what a choice should be made on anyway.
    """
    lines = []
    for i, gif in enumerate(pool[:limit], start=1):
        if gif.tags:
            lines.append(f"{i}. {', '.join(gif.tags)}")
    return "\n".join(lines)


def choose(pool: list[Gif], number: int) -> Gif | None:
    """Resolve the model's pick. Out of range is a miss, not a fallback.

    Deliberately not "closest match" or "first one": a GIF nobody chose is the
    approximate reaction this whole feature exists to avoid.
    """
    if number < 1 or number > len(pool):
        return None
    return pool[number - 1]


def by_tag(pool: list[Gif], term: str) -> Gif | None:
    """Any GIF carrying a tag, at random among those that do."""
    term = term.strip().lower()
    if not term:
        return None
    matches = [g for g in pool if any(term == t for t in g.tags)]
    return random.choice(matches) if matches else None
