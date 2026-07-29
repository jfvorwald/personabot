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
    replies = [r for r in records if r.get("kind") == "reply"]
    quoted = sum(1 for r in replies if r.get("as_reply"))
    return {
        "total": len(records),
        "kinds": dict(kinds),
        "paths": dict(paths),
        "passed": kinds.get("pass", 0),
        "replied": kinds.get("reply", 0),
        # Discord's reply feature is meant to be rare. "Rare" is an opinion
        # until it is a number, so it gets counted.
        "quote_replied": quoted,
        "quote_reply_share": round(quoted / len(replies), 2) if replies else 0.0,
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


# --- the backlog ------------------------------------------------------------
#
# Proposals accumulate rather than being replaced. A snapshot rewritten every
# run means anything not acted on immediately is gone by tomorrow, which turns
# "I will get to that later" into "that never happened".
#
# Kept as markdown because a human edits it: the status marker in each heading
# is how Jack says done or not doing this, and nothing here overwrites what he
# has written underneath.

STATUSES = ("open", "done", "dropped")

_HEADING = re.compile(r"^##\s*\[(\w+)\]\s*(.+?)\s*$", re.MULTILINE)
_FIELD = re.compile(r"^-\s*(\w[\w ]*?):\s*(.*)$")


def slug(title: str) -> set:
    """The content words of a title, for comparing two wordings of one idea."""
    return {w for w in words_in(title) if len(w) > 3 and w not in COMMON}


def same_proposal(a: str, b: str, threshold: float = 0.5) -> bool:
    """Are these two titles the same suggestion, worded differently?

    Exact matching does not survive the model rephrasing itself between runs -
    "Cut the \"still\" tic" and "Cut the tic of saying still" are one item, and
    two entries for it defeats the point of counting repeats.

    Overlap against the *shorter* title, so a terse rewording of a wordy
    proposal still matches.
    """
    left, right = slug(a), slug(b)
    if not left or not right:
        return False
    return len(left & right) / min(len(left), len(right)) >= threshold


def parse_proposals(text: str) -> list[dict]:
    """Pull items out of what the model produced.

    Forgiving by design: a missing field costs that field, not the proposal.
    """
    items = []
    blocks = re.split(r"^##\s+", text, flags=re.MULTILINE)
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        item = {"title": lines[0].strip(), "where": "", "why": "", "change": ""}
        for line in lines[1:]:
            for key in ("WHERE", "WHY", "CHANGE"):
                if line.strip().upper().startswith(key + ":"):
                    item[key.lower()] = line.split(":", 1)[1].strip()
        if item["title"]:
            items.append(item)
    return items


def parse_backlog(text: str) -> list[dict]:
    """Read the backlog back, including anything a human added to it."""
    items = []
    for match in _HEADING.finditer(text or ""):
        start = match.end()
        nxt = _HEADING.search(text, start)
        body = text[start : nxt.start() if nxt else len(text)]
        item = {
            "status": match.group(1).lower(),
            "title": match.group(2).strip(),
            "where": "",
            "why": "",
            "change": "",
            "first": "",
            "last": "",
            "seen": 1,
            "notes": "",
        }
        notes = []
        for line in body.strip().splitlines():
            field = _FIELD.match(line.strip())
            if field:
                key, value = field.group(1).strip().lower(), field.group(2).strip()
                if key in ("where", "why", "change", "first", "last"):
                    item[key] = value
                    continue
                if key == "seen":
                    item["seen"] = int(value.split()[0]) if value.split() else 1
                    continue
            if line.strip():
                notes.append(line.rstrip())
        item["notes"] = "\n".join(notes)
        items.append(item)
    return items


def merge_backlog(existing: list[dict], incoming: list[dict], today: str) -> list[dict]:
    """Fold today's proposals into what is already there.

    A proposal that keeps coming back is worth knowing about, so a repeat bumps
    a counter rather than adding a duplicate. A decision already made is never
    reopened: something marked done or dropped stays that way even if the model
    suggests it again, because reversing Jack's call silently is worse than
    losing a suggestion.
    """
    kept = [dict(item) for item in existing]
    for item in incoming:
        found = next(
            (k for k in kept if same_proposal(k["title"], item["title"])), None
        )
        if found is not None:
            found["seen"] = found.get("seen", 1) + 1
            found["last"] = today
            # Only fill in fields that were empty; never overwrite a human edit.
            for field in ("where", "why", "change"):
                if not found.get(field):
                    found[field] = item.get(field, "")
            continue
        kept.append({
            "status": "open",
            "title": item["title"],
            "where": item.get("where", ""),
            "why": item.get("why", ""),
            "change": item.get("change", ""),
            "first": today,
            "last": today,
            "seen": 1,
            "notes": "",
        })
    # Open first, then most-repeated: the thing suggested five times and still
    # not done is the one worth looking at.
    order = {"open": 0, "dropped": 1, "done": 2}
    return sorted(
        kept,
        key=lambda i: (order.get(i.get("status", "open"), 0), -i.get("seen", 1)),
    )


def render_backlog(items: list[dict]) -> str:
    """Write it back out, human-editable.

    Change [open] to [done] or [dropped] to record a decision. Anything written
    underneath an item is kept.
    """
    out = [
        "# Improvement backlog",
        "",
        "Proposals, accumulated. **Nothing here has been applied.**",
        "",
        "Change `[open]` to `[done]` or `[dropped]` to record a decision - a",
        "decision is never reopened, even if the same thing gets proposed again.",
        "Anything you write under an item is kept.",
        "",
    ]
    for item in items:
        out.append(f"## [{item.get('status', 'open')}] {item['title']}")
        if item.get("where"):
            out.append(f"- where: {item['where']}")
        if item.get("why"):
            out.append(f"- why: {item['why']}")
        if item.get("change"):
            out.append(f"- change: {item['change']}")
        seen = item.get("seen", 1)
        out.append(f"- seen: {seen} time{'s' if seen != 1 else ''}")
        # Written as their own fields rather than folded into the line above:
        # this file is read back and merged, and a date parsed out of prose is
        # a date that stops parsing the first time someone edits the prose.
        if item.get("first"):
            out.append(f"- first: {item['first']}")
        if item.get("last"):
            out.append(f"- last: {item['last']}")
        if item.get("notes"):
            out.append("")
            out.append(item["notes"])
        out.append("")
    return "\n".join(out)
