"""What is going on outside this channel.

A person in a group chat has read the news that morning. Jaq had no idea a
storm had happened the week somebody's PC died in one, which is the specific
gap this closes: not being able to discuss the news, but not knowing the world
moved.

Shaped like `changelog.py` rather than like `brain.py`. It fetches on a
schedule, writes one small file, and the live bot only ever reads it. Nothing
here is on the reply path, so a failed fetch, a missing file or a stale one
costs the bot nothing at all - it simply does not know what happened today,
which is a state real people are in constantly.

The digest is filtered when it is written, not when it is used. Politics, war,
disasters with casualties, crime and death never enter the file, so there is
nothing in the prompt for the persona to be tasteless about. That is the same
bargain guard.py makes: a rule the model can be talked out of is not a control,
and the cheapest control is having nothing there to find.
"""

from __future__ import annotations

import logging
import os
import time

import guard
from paths import at_root

log = logging.getLogger("personabot")

DIGEST_FILE = os.getenv("WORLD_FILE", "world.md")


def path() -> str:
    return at_root(DIGEST_FILE)


def age_hours() -> float | None:
    """How old the digest is, or None if there isn't one."""
    try:
        return (time.time() - os.path.getmtime(path())) / 3600
    except OSError:
        return None


def load(max_chars: int = 2000, stale_hours: float = 36.0) -> str:
    """The digest, if there is a fresh one. Empty string otherwise.

    Stale is treated as absent rather than as better-than-nothing. Yesterday's
    news presented as today's is worse than no news: it is the one failure
    mode here that a reader can actually catch, because they were there.
    """
    age = age_hours()
    if age is None:
        return ""
    if stale_hours and age > stale_hours:
        log.info("World digest is %.0fh old; not using it", age)
        return ""
    try:
        with open(path(), encoding="utf-8") as f:
            text = f.read().strip()
    except OSError:
        return ""
    if not text or _is_blank(text):
        return ""
    if len(text) <= max_chars:
        return text
    # Whole lines only. A bullet cut off mid-word reads as a broken prompt
    # rather than as a short one, and the last one is always the least
    # important thing in the file.
    kept: list[str] = []
    spent = 0
    for line in text.splitlines():
        if spent + len(line) + 1 > max_chars:
            break
        kept.append(line)
        spent += len(line) + 1
    if not kept:
        # One line longer than the whole budget. Whole-lines-only must not
        # mean no lines, so this is the one case that gets cut mid-word.
        return text[:max_chars]
    return "\n".join(kept)


def _is_blank(text: str) -> bool:
    """Headings with nothing under them are not knowledge.

    Same rule the personnel loader and the brain both apply, for the third
    time: a fetch that returned nothing usable should read as absent rather
    than as a promise of news followed by a blank.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or set(stripped) <= {"-", "*", "="}:
            continue
        return False
    return True


def _from_first_bullet(text: str) -> str:
    """Drop everything before the first bullet.

    A live fetch opened with "Good, I have the earlier results saved. Let me
    parse and inspect all of them now instead of making new search calls." -
    the model narrating its own process, followed by a preamble sentence. The
    bullets outnumbered it so the shape check passed, and it would have gone
    into the prompt under a heading promising world events.

    A digest starts at its first bullet by definition, so anything above that
    line is not news.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(("-", "*")):
            return "\n".join(lines[i:]).strip()
    return text.strip()


def is_digest(text: str) -> bool:
    """Does this look like a digest, or like a message about one?

    The first live fetch hit the search tool's usage limit and the model, given
    no way to comply, wrote a paragraph of apology addressed to a person:
    "I tried to pull fresh headlines just now, but... Want me to give it
    another shot?". That is prose, so a blank-check passes it, and it would
    have been injected under a heading promising things that happened in the
    world.

    So the shape is checked rather than trusted. A digest is bullets. Anything
    that is mostly sentences is a message, and a message is not news.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    bullets = [ln for ln in lines if ln.startswith(("-", "*")) and len(ln) > 3]
    if len(bullets) < 3:
        return False
    # Most of it has to be the bullets. Headings are allowed; paragraphs of
    # explanation around them are the failure this is looking for.
    other = [ln for ln in lines if ln not in bullets and not ln.startswith("#")]
    return len(bullets) > len(other)


def describe() -> str:
    age = age_hours()
    if age is None:
        return "none yet"
    return f"{os.path.getsize(path())} bytes, {age:.1f}h old"


async def refresh(
    client, model: str, prompt: str, max_searches: int = 5,
    max_tokens: int = 8000,
) -> bool:
    """Search for what happened, write the digest. True if it wrote one.

    Never raises. This runs on a timer in the live bot, and a bot that falls
    over because a search failed is worse than one that does not know what
    happened today.
    """
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=prompt,
            tools=[{
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": max_searches,
            }],
            messages=[{"role": "user", "content": "What has been going on?"}],
        )
    except Exception:
        log.exception("World refresh failed; keeping the previous digest")
        return False

    if response.stop_reason == "refusal":
        log.warning("World refresh declined: %s", response.stop_details)
        return False
    if response.stop_reason == "max_tokens":
        # Server-side search results are content blocks and count against the
        # budget, so a wide sweep can spend the whole allowance before the
        # model writes a word. The first symptom of this was "came back empty",
        # which sent the diagnosis somewhere else entirely.
        log.warning(
            "World refresh ran out of tokens before writing anything - raise "
            "WORLD_MAX_TOKENS or lower WORLD_SEARCH_MAX"
        )
        return False

    text = "".join(
        b.text for b in response.content if getattr(b, "type", "") == "text"
    ).strip()
    if not text or _is_blank(text):
        log.warning("World refresh came back empty; keeping the previous digest")
        return False
    if not is_digest(text):
        # Usually the search failing and the model explaining itself instead.
        log.warning(
            "World refresh returned prose rather than a digest; keeping the "
            "previous one (%s...)", text[:70].replace("\n", " ")
        )
        return False

    # This goes into the system prompt, where an em dash is not a style
    # violation but a lesson: every one the model reads teaches it the habit,
    # and it is the most recognisable machine tell there is. The digest is
    # generated rather than authored, so tests/test_style.py never sees it.
    text = guard.de_dash(_from_first_bullet(text))

    try:
        with open(path(), "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        log.exception("Could not write the world digest")
        return False

    searches = sum(
        1 for b in response.content if getattr(b, "type", "") == "server_tool_use"
    )
    log.info("World digest refreshed: %d chars, %d search(es)", len(text), searches)
    return True
