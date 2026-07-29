"""What Jaq is actually doing, measured rather than guessed at.

The model cannot see its own habits. Every reply is a fresh single-turn call
with no memory of the last forty, so a verbal tic is invisible from the inside
and obvious from the outside: across one evening "still" opened 37% of his
messages, and nothing in the system could have noticed.

So the measuring is arithmetic and the judging is a separate step. The numbers
here are facts about what was posted - free, deterministic, and the same every
time they are computed. What to do about them is a question for a model, and
what to actually change is a question for Jack.

Two halves, deliberately:

    metrics    pure functions over a list of messages. No IO, no Discord, no
               model. This is the part that can be trusted.
    the log    one line appended per reply by the live bot, recording things
               the channel history cannot show afterwards - which path a reply
               took, what the dice said, whether the guard blocked something.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter

# Words too ordinary to be a tic. A list this short is deliberate: the point is
# to catch "still" and "already", not to build a stopword corpus.
COMMON = {
    "the", "a", "an", "and", "but", "or", "of", "in", "on", "at", "to", "for",
    "with", "from", "into", "that", "this", "these", "those", "it", "its",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "you", "your", "i", "me", "my", "we", "he", "she", "they", "them", "his",
    "her", "their", "not", "no", "so", "if", "as", "than", "then", "there",
    "what", "when", "where", "who", "how", "why", "all", "just", "like",
}

WORD = re.compile(r"[a-z0-9'\-]+")


def words_in(text: str) -> list[str]:
    return WORD.findall(text.lower())


def overused(messages: list[str], min_share: float = 0.15) -> list[tuple[str, float]]:
    """Words appearing in more than `min_share` of messages.

    Share of *messages*, not share of words: a word used four times in one
    message is a sentence, and a word used once in half of them is a tic.
    """
    if not messages:
        return []
    counts: Counter = Counter()
    for text in messages:
        for word in {w for w in words_in(text) if len(w) > 3 and w not in COMMON}:
            counts[word] += 1
    found = [
        (word, n / len(messages))
        for word, n in counts.items()
        if n / len(messages) >= min_share and n > 2
    ]
    return sorted(found, key=lambda p: -p[1])


def repeated_phrases(
    messages: list[str], size: int = 3, min_count: int = 3
) -> list[tuple[str, int]]:
    """Multi-word phrases used again and again.

    Catches the thing single words miss: a running joke being restated in the
    same words every time, which reads as a stuck record rather than a callback.
    """
    counts: Counter = Counter()
    for text in messages:
        tokens = words_in(text)
        seen = {
            " ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)
        }
        for phrase in seen:
            counts[phrase] += 1
    found = [(p, n) for p, n in counts.items() if n >= min_count]
    return sorted(found, key=lambda p: -p[1])


def opening_habits(
    messages: list[str], min_share: float = 0.12
) -> list[tuple[str, float]]:
    """How often messages start the same way.

    A predictable opener is the most conspicuous tell there is, because it is
    the first thing anyone reads.
    """
    if not messages:
        return []
    counts: Counter = Counter()
    for text in messages:
        tokens = words_in(text)
        if tokens:
            counts[tokens[0]] += 1
    return sorted(
        [(w, n / len(messages)) for w, n in counts.items() if n / len(messages) >= min_share and n > 2],
        key=lambda p: -p[1],
    )


def length_profile(messages: list[str]) -> dict:
    """Median and worst-case length. Drift upward is the usual failure."""
    lengths = sorted(len(m) for m in messages)
    if not lengths:
        return {"count": 0, "median": 0, "longest": 0, "over_300": 0}
    return {
        "count": len(lengths),
        "median": lengths[len(lengths) // 2],
        "longest": lengths[-1],
        "over_300": sum(1 for n in lengths if n > 300),
    }


def engagement(records: list[dict]) -> dict:
    """What the live bot saw itself do, aggregated.

    Counts of each path taken and each decision made. Deliberately blunt: this
    is a description of behaviour, not a score.
    """
    kinds: Counter = Counter(r.get("kind", "?") for r in records)
    paths: Counter = Counter(r.get("path", "?") for r in records if r.get("kind") == "reply")
    return {
        "total": len(records),
        "kinds": dict(kinds),
        "paths": dict(paths),
        "passed": kinds.get("pass", 0),
        "replied": kinds.get("reply", 0),
    }


# --- the log ----------------------------------------------------------------
#
# Appended by the live bot, one line per decision. JSONL rather than a document
# because it is written constantly and read once a day, and a partial line at
# the end of a crashed write costs one record instead of the file.


def record(event: dict, path: str) -> None:
    """Append one observation. Never raises - this must not break a reply."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, separators=(",", ":")) + "\n")
    except (OSError, TypeError, ValueError):
        # Losing an observation is not worth a failed message in the channel.
        pass


def read_records(path: str, since: str = "") -> list[dict]:
    """Every observation, optionally only those on or after an ISO timestamp.

    Skips unparseable lines rather than failing: a log written by an appending
    process will occasionally have a torn last line.
    """
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if since and event.get("at", "") < since:
                    continue
                out.append(event)
    except OSError:
        return []
    return out
