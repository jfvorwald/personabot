"""Last check before anything reaches the channel.

The prompt tells the model to keep things confidential. This assumes that will
eventually fail - a long enough conversation, a clever enough framing, or an
ordinary mistake - and checks the actual outgoing text instead. A rule the
model can be talked out of is not a control; a string comparison is.

Deliberately small. It scans for a short list of things that must never appear
and refuses the message if it finds one. It does not try to detect "talking
about the system" in general, which is a judgement call and belongs in the
prompt where it can be argued with.
"""

from __future__ import annotations

import re
import unicodedata

# Anything shorter than this is too likely to appear innocently in normal
# speech, and a guard that blocks ordinary messages gets switched off.
MIN_TERM_LENGTH = 4

# Written as escapes so this file does not contain the thing it removes.
DASHES = {
    "\u2014": "-",   # em dash, the most recognisable machine tell there is
    "\u2013": "-",   # en dash, the same tell wearing a smaller hat
    "\u2015": "-",   # horizontal bar
}


def de_dash(text: str) -> str:
    """Replace typographic dashes with hyphens on the way out.

    The rule was enforced in the prompt files and asked for in the prompt, and
    nothing checked what the model actually produced. That is the same shape
    as every other failure in this project: an instruction where a check was
    needed. The improvement pass proved the point by writing four em dashes
    into its own output in a single run.

    A substitution rather than a refusal. Blocking a whole message over
    punctuation would be a worse outcome than the punctuation.
    """
    if not text:
        return text
    for dash, replacement in DASHES.items():
        text = text.replace(dash, replacement)
    return text


# Column alignment in a table the model drew. Asking for it in the prompt does
# not work: a model cannot count characters, so rows drift by one or two and
# the grid shears. Alignment is the entire joke in a spreadsheet, so this is
# the same bargain the rest of this file makes - the prompt asks, and this
# makes it true afterwards.
#
# Deliberately timid. ASCII art uses pipes as drawing strokes, and a drawing
# run through a table formatter is destroyed, so a run has to look distinctly
# like a table before anything is touched: a horizontal rule, a steady column
# count, and cells with actual words in them.
_RULE_CHARS = set("+-=| :")
_FENCE = "```"
# Discord wraps a code block on a phone somewhere around here, and a wrapped
# table is unreadable in a way a merely wide one is not - every row breaks in a
# different place and the grid stops existing. The prompt asks for narrow
# columns and is ignored, because staying inside a width means counting
# characters. So it is counted here instead.
MAX_TABLE_WIDTH = 58
# Never shrink a column past this. Below it the cells stop being words and the
# table is no more readable than the wrapped one it was trying to avoid, at
# which point letting it be too wide is the better failure.
MIN_COLUMN_WIDTH = 4


def _is_rule(line: str) -> bool:
    """A +----+----+ or |----|----| separator."""
    stripped = line.strip()
    if not stripped or not set(stripped) <= _RULE_CHARS:
        return False
    return stripped.count("-") + stripped.count("=") >= 3


def _is_row(line: str) -> bool:
    """| a | b | - at least two cells, bordered on both sides."""
    stripped = line.strip()
    return (
        stripped.startswith("|")
        and stripped.endswith("|")
        and stripped.count("|") >= 3
    )


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip()[1:-1].split("|")]


def _fit_width(widths: list[int]) -> list[int]:
    """Shave the widest columns until the table fits on a phone.

    Widest first, one character at a time, so the cost falls on the column
    with the most slack rather than on whichever happens to be last. Gives up
    rather than shaving anything to nothing.
    """
    widths = list(widths)

    def total(ws: list[int]) -> int:
        return sum(w + 3 for w in ws) + 1

    while total(widths) > MAX_TABLE_WIDTH:
        widest = max(widths)
        if widest <= MIN_COLUMN_WIDTH:
            break
        widths[widths.index(widest)] = widest - 1
    return widths


def _align_run(lines: list[str]) -> list[str]:
    """Re-pad one run of table lines, or hand it back untouched."""
    rows = [ln for ln in lines if not _is_rule(ln) and _is_row(ln)]
    if len(rows) < 2:
        return lines

    counts = [len(_cells(r)) for r in rows]
    modal = max(set(counts), key=counts.count)
    if modal < 2:
        return lines
    keep = [r for r in rows if len(_cells(r)) == modal]
    if len(keep) < 2:
        return lines

    # A drawing has pipes but almost no words between them. A table has words.
    cells = [c for r in keep for c in _cells(r)]
    worded = sum(1 for c in cells if any(ch.isalnum() for ch in c))
    if worded * 2 < len(cells):
        return lines

    widths = [0] * modal
    for row in keep:
        for i, cell in enumerate(_cells(row)):
            widths[i] = max(widths[i], len(cell))
    widths = _fit_width(widths)

    indent = lines[0][: len(lines[0]) - len(lines[0].lstrip())]
    out = []
    for line in lines:
        if _is_rule(line):
            stripped = line.strip()
            fill = "=" if "=" in stripped else "-"
            junction = "+" if "+" in stripped else "|"
            out.append(
                indent + junction + junction.join(fill * (w + 2) for w in widths) + junction
            )
        elif _is_row(line) and len(_cells(line)) == modal:
            padded = " | ".join(
                c[:w].ljust(w) for c, w in zip(_cells(line), widths)
            )
            out.append(f"{indent}| {padded} |")
        else:
            # A title line, a footnote, or a row with the wrong number of
            # cells. Left exactly as written rather than guessed at.
            out.append(line)
    return out


def align_tables(text: str) -> str:
    """Straighten any table the model drew inside a code block.

    Only inside a fence: a stray pipe in ordinary conversation is punctuation,
    and reflowing a sentence around it would be worse than a crooked table.
    """
    if _FENCE not in text:
        return text
    lines = text.split("\n")
    fences = [i for i, ln in enumerate(lines) if ln.lstrip().startswith(_FENCE)]
    if len(fences) < 2:
        return text

    inside = set()
    for opener, closer in zip(fences[::2], fences[1::2]):
        inside.update(range(opener + 1, closer))

    out, run, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        if i in inside and (_is_row(line) or _is_rule(line)):
            run.append(line)
        else:
            if run:
                out.extend(_align_run(run))
                run = []
            out.append(line)
        i += 1
    if run:
        out.extend(_align_run(run))
    return "\n".join(out)


def _normalise(text: str) -> str:
    """Fold case, unicode, and separators so trivial obfuscation still matches.

    Catches "J-a-c-k V o r w a l d" and fullwidth variants without pretending
    to defeat a determined encoder - that is what the leak-proof secrets below
    are for.
    """
    folded = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[\s\-_.*`~|]+", "", folded)


def find_leak(text: str, secrets: list[str], terms: list[str]) -> str | None:
    """Return a label for the first forbidden thing found, or None.

    `secrets` are exact-match credentials - a token or key appearing anywhere
    is fatal regardless of context. `terms` are names and identifiers, matched
    after normalisation so spacing tricks do not slip past.
    """
    if not text:
        return None

    for secret in secrets:
        if secret and len(secret) >= 8 and secret in text:
            return "credential"

    packed = _normalise(text)
    for term in terms:
        if not term or len(term) < MIN_TERM_LENGTH:
            continue
        if _normalise(term) in packed:
            return f"forbidden term ({term})"
    return None
