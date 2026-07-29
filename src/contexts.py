"""Worlds a picture can be set in, defined in markdown rather than in code.

A channel has recurring subjects, and a picture about one of them lands better
when it looks like it belongs to that subject. Rather than teach the persona
about every one of them, each is a file: what the world looks like, what fires
it, and how often.

Adding one is writing a file. No code changes, no restart-time registration,
nothing here to edit - which is the point, because the person who knows what
the channel talks about is not necessarily the person editing Python.

Consulted only when a picture is already being offered, so on the overwhelming
majority of messages this module does nothing at all.

    ---
    name: warcraft
    when: wow, azeroth, raid, mythic, guild, loot, wipe
    chance: 0.6
    ---

    Everything below the second marker is the context itself.

`when` is what makes a context fire only where it makes sense. `chance` is what
stops it firing every single time it could, because a channel where every
picture is in the same register has a house style nobody chose.
"""

from __future__ import annotations

import logging
import os
import random
import re

from paths import at_root

log = logging.getLogger("personabot.contexts")

CONTEXTS_DIR = "contexts"
# Tracked files that document the format rather than defining a world. Skipped
# so a fresh clone does not start rendering everything as the example.
NOT_CONTEXTS = {"readme.md", "example.md"}

_MARKER = "---"


class Context:
    def __init__(self, name: str, triggers: list[str], chance: float, body: str):
        self.name = name
        self.triggers = triggers
        self.chance = chance
        self.body = body

    def matches(self, text: str) -> bool:
        """Is this world what the room is currently talking about?

        Whole-word matching: "raid" should not fire on "afraid", and a context
        that fires on a substring of an ordinary word fires constantly.
        """
        lowered = text.lower()
        return any(
            re.search(rf"\b{re.escape(t)}\b", lowered) for t in self.triggers
        )


def _parse(text: str, filename: str) -> Context | None:
    """Pull a context out of a markdown file, or None if it is not one.

    Deliberately forgiving. These are written by hand by someone describing a
    world, not filling in a form, so a missing field takes a default and a
    malformed file is skipped with a line in the log rather than stopping the
    bot from starting.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _MARKER:
        log.warning("%s has no metadata block; skipped", filename)
        return None

    fields: dict[str, str] = {}
    body_start = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == _MARKER:
            body_start = i + 1
            break
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip().lower()] = value.strip()
    if body_start is None:
        log.warning("%s never closes its metadata block; skipped", filename)
        return None

    body = "\n".join(lines[body_start:]).strip()
    if not body:
        log.warning("%s has no body; skipped", filename)
        return None

    triggers = [t.strip().lower() for t in fields.get("when", "").split(",") if t.strip()]
    if not triggers:
        log.warning("%s lists no 'when' triggers, so it can never fire", filename)
        return None

    try:
        chance = float(fields.get("chance", "1"))
    except ValueError:
        chance = 1.0
    name = fields.get("name") or os.path.splitext(filename)[0]
    return Context(name, triggers, max(0.0, min(1.0, chance)), body)


def load_all() -> list[Context]:
    """Every context on disk. Read fresh, so editing one takes effect at once.

    Contexts are content, like the brain's profiles, and content should not
    need a restart to change. The read is a handful of small files and only
    happens when a picture is already on the table.
    """
    directory = at_root(CONTEXTS_DIR)
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []

    found = []
    for filename in names:
        if not filename.lower().endswith(".md") or filename.lower() in NOT_CONTEXTS:
            continue
        try:
            with open(os.path.join(directory, filename), encoding="utf-8") as f:
                parsed = _parse(f.read(), filename)
        except OSError:
            log.warning("Could not read %s", filename)
            continue
        if parsed:
            found.append(parsed)
    return found


def pick(text: str, roll: float | None = None) -> Context | None:
    """Choose a world for this picture, or none at all.

    Two gates. The context has to fit what is being talked about, and then it
    still has to win its own chance - a channel where every picture comes out
    in the same register has acquired a house style nobody chose.

    Where several fit, one is drawn at random rather than the first
    alphabetically, so a file named early does not quietly own every overlap.
    """
    eligible = [c for c in load_all() if c.matches(text)]
    if not eligible:
        return None
    chosen = random.choice(eligible)
    if (roll if roll is not None else random.random()) > chosen.chance:
        log.info("Context %s fit but did not fire", chosen.name)
        return None
    return chosen
