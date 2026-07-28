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
