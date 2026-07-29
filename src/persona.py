"""Reading the character off disk.

Three small loaders kept together because they answer the same question:
what does this bot think it is, and when does it speak. Separated from the
client so the files can be reloaded or swapped without touching the
machinery that uses them.
"""

from __future__ import annotations

import os
import sys
from datetime import time as dtime

from config import DM_PERSONA_FILE, PERSONA_FILE, PSYCHOLOGY_FILE, TIMEZONE, VOCAB
from prompts import VOCAB_BLOCK
from paths import at_root

def load_post_times() -> list[dtime]:
    """Parse POST_TIMES ('09:00,13:15,19:30') into tz-aware time objects."""
    raw = os.getenv("POST_TIMES", "09:00")
    times = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        hour, minute = chunk.split(":")
        times.append(dtime(hour=int(hour), minute=int(minute), tzinfo=TIMEZONE))
    if not times:
        raise ValueError("POST_TIMES is empty")
    return times

def load_psychology() -> str:
    """Conversation mechanics. Optional; missing file is not an error."""
    path = at_root(PSYCHOLOGY_FILE)
    if not os.path.exists(path):
        return ""
    with open(path) as f:
        return f.read().strip()

def load_persona() -> str:
    with open(PERSONA_FILE, encoding="utf-8") as f:
        persona = f.read().strip()
    if not persona:
        raise ValueError(f"{PERSONA_FILE} is empty")
    return persona


def load_vocab() -> str:
    """Jack's current word list, as a prompt block. Empty if he hasn't set one."""
    if not VOCAB:
        return ""
    return VOCAB_BLOCK.format(words="\n".join(f"- {w}" for w in VOCAB))


def load_dm_persona() -> str:
    """Who Jaq is in a direct message with the person who made him.

    Deliberately a separate document from persona.md. The channel persona is
    written for an audience - a character doing a bit in front of a room - and
    a private conversation is not that with the volume lowered, it is a
    different thing entirely.

    Absent, this returns "" and bot.py falls back to a plain default rather
    than to the channel character. That fallback matters: a missing file must
    not silently put the performer back in the room.
    """
    try:
        with open(at_root(DM_PERSONA_FILE), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""
