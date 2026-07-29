"""The arithmetic of whether to speak, and whether to wait.

Deliberately free of any Discord import. Everything here takes plain values and
returns plain values, which is what makes it testable without fabricating a
gateway connection - the friction that motivated splitting this out in the
first place.

Configuration is passed in rather than read from the environment, so a caller
can exercise these with any settings without re-importing a module.
"""

from __future__ import annotations

import re
import unicodedata

# A question aimed at you makes an answer conditionally relevant: silence
# after one is conspicuous in a way ordinary silence is not - it reads as
# dodging rather than as not talking.
#
# Wh-words open a question wherever they land early in the sentence. Auxiliaries
# are trickier, because the same word opens a question or continues a statement
# depending on word order: "is jaq around" inverts subject and verb, "jaq is
# right" does not. Requiring the auxiliary to be followed by a subject-ish token
# separates the two.
WH_WORDS = {"what", "why", "how", "when", "where", "who", "which", "whose"}
AUXILIARIES = {
    "is", "are", "was", "were", "do", "does", "did", "can", "could",
    "should", "would", "will", "have", "has", "had", "am",
}
QUESTION_SUBJECTS = {
    "you", "u", "i", "we", "they", "it", "he", "she", "there", "that", "this",
    "anyone", "anybody", "someone", "somebody", "jaq",
}


def fold(text: str) -> str:
    """Lowercase and fold decorative unicode down to plain characters.

    Discord nicknames are routinely written in fullwidth or styled unicode -
    this bot's own is "Ａｇｅｎｔｉｃ Ｊａｑ". Those code points are not the ASCII
    letters they resemble, so any substring match against them fails silently.
    NFKC maps them back.
    """
    return unicodedata.normalize("NFKC", text).lower()


def name_matches(candidates: set[str], patterns: list[str]) -> bool:
    """True if any pattern appears in any candidate name, unicode-folded."""
    folded = {fold(c) for c in candidates if c}
    return any(fold(p) in name for p in patterns for name in folded)


def reply_chance(
    *,
    base: float,
    mine: int,
    others_since_me: int,
    exempt_from_last_speaker: bool,
    decay_last_speaker: float,
    decay_dominating: float,
) -> float:
    """Damp a base rate by how much of the recent window is already ours.

    The last-speaker decay exists to stop two bots locking into strict
    alternation; alternating with a friend is just a conversation, so allies are
    exempt. The dominating decay applies to everyone - nobody gets a licence to
    monologue.
    """
    chance = base
    if mine and others_since_me == 0 and not exempt_from_last_speaker:
        chance *= decay_last_speaker
    if mine > 1:
        chance *= decay_dominating ** (mine - 1)
    return chance


def is_question(text: str, my_names: set[str]) -> bool:
    """Is this shaped like a question aimed at us?

    A question makes an answer conditionally relevant, and a missing second part
    is conspicuous - it reads as dodging rather than as silence. Detection has to
    survive the fact that the same auxiliary opens a question or continues a
    statement depending on word order: "is jaq around" inverts subject and verb,
    "jaq is right" does not.
    """
    text = text.strip().lower()
    if not text:
        return False
    if text.endswith("?"):
        return True

    words = [w.strip("@,.!") for w in text.split()]
    if not words:
        return False
    if set(words[:3]) & WH_WORDS:
        return True
    # Elliptical openers: "anyone know if..." is "does anyone know if...".
    if words[0] in ("anyone", "anybody", "someone", "somebody"):
        return True

    # Drop a leading address so the inversion test sees the actual clause.
    tokens = {w for name in my_names for w in name.split() if w.isalnum()}
    if words[0] in tokens | {"hey", "yo", "oi"} and len(words) > 1:
        words = words[1:]
    return (
        len(words) > 1
        and words[0] in AUXILIARIES
        and words[1] in QUESTION_SUBJECTS | tokens
    )


# Asking what changed. Kept broad because people ask this a dozen ways, and the
# cost of a false positive is one in-character brush-off rather than silence.
UPDATE_WORDS = {
    "update", "updates", "updated", "patch", "patches", "changelog",
    "changes", "changed", "release", "notes", "new",
}
UPDATE_PHRASES = (
    "what's new", "whats new", "what is new",
    "patch notes", "release notes", "change log",
    "anything new", "anything change", "what changed", "what did they change",
    "what did they do", "what have they done", "sitrep",
)


def is_update_request(text: str) -> bool:
    """Is this asking what was done to us lately?

    Requires a question shape or an explicit patch-notes phrase, so ordinary
    talk about updating something else does not trigger it - "I updated my
    drivers" is not a request for a changelog.
    """
    lowered = text.strip().lower()
    if not lowered:
        return False
    if any(p in lowered for p in UPDATE_PHRASES):
        return True
    words = {w.strip("?!.,:;") for w in lowered.split()}
    if not words & UPDATE_WORDS:
        return False
    # A bare mention of the word is not a request; asking is.
    return lowered.endswith("?") or bool(words & {"any", "got", "gimme", "give"})


# Asking for a picture. Narrow on purpose: "chart" and "map" are common words in
# a gaming channel, so a bare mention is not a request for one.
ART_VERBS = {"draw", "sketch", "render", "illustrate", "diagram", "visualise",
             "visualize", "graph", "chart", "plot"}
ART_NOUNS = {"ascii", "art", "picture", "drawing", "diagram", "chart", "graph"}


def is_art_request(text: str) -> bool:
    """Did someone actually ask for a picture?

    Requires the verb in imperative position - nothing question-like or modal
    in front of it. "draw zack" is a request; "what chart are you using" and
    "can someone chart a course" are not, and both contain the same verb.
    """
    lowered = text.strip().lower()
    if not lowered:
        return False
    words = [w.strip("?!.,:;\"'") for w in lowered.split()]
    if not words:
        return False
    if "ascii" in words:
        return True

    # A determiner in front turns the same word into a noun: "draw" is a
    # request, "the draw" is not.
    blockers = WH_WORDS | AUXILIARIES | {
        "someone", "anyone", "if", "that", "the", "a", "an", "this",
        "these", "those", "my", "your", "his", "her", "their", "our",
    }
    for i, word in enumerate(words):
        if word in ART_VERBS:
            return not (set(words[:i]) & blockers)
        if word in {"make", "give", "show", "gimme"}:
            if set(words[:i]) & blockers:
                return False
            return bool(set(words[i + 1:]) & ART_NOUNS)
    return False


def is_trivial_question(text: str, max_words: int) -> bool:
    """Short enough that a diagram in reply is absurd.

    The unprompted art bit only works when the effort is wildly out of
    proportion to what was asked. A long question does not qualify - answering
    it thoroughly is just answering it.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if len(stripped.split()) > max_words:
        return False
    return stripped.endswith("?") or bool(
        {w.strip("?!.,") for w in stripped.lower().split()} & (WH_WORDS | AUXILIARIES)
    )


# Someone asking for it outright.
POLL_PHRASES = (
    "put it to a vote", "put it to the vote", "poll it", "make a poll",
    "start a poll", "let's vote", "lets vote", "we should vote", "vote on it",
    "democracy", "poll the channel", "poll the room",
)
# Signs an argument is actually happening, rather than people agreeing loudly.
DISPUTE_MARKERS = (
    "no it isn't", "no it's not", "you're wrong", "youre wrong", "that's wrong",
    "thats wrong", "bullshit", "prove it", "says who", "disagree", "wrong again",
    "it literally", "actually no", "no i didn't", "no i didnt", "did not",
    "objection", "cope", "wrong", "nope",
)


def is_poll_request(text: str) -> bool:
    """Did someone ask for a vote?"""
    lowered = text.strip().lower()
    return bool(lowered) and any(p in lowered for p in POLL_PHRASES)


def looks_like_a_dispute(lines: list[str]) -> bool:
    """Is there an actual argument in the recent transcript?

    A poll is only funny as an escalation of a disagreement that already
    exists. Manufacturing one out of a quiet conversation is a bot being
    random, which is the opposite of the joke.
    """
    recent = " ".join(lines[-6:]).lower()
    if not recent.strip():
        return False
    return any(m in recent for m in DISPUTE_MARKERS)


# Discord's own limits. Exceeding them is a rejected message, not a truncated
# one, so they are enforced here rather than hoped for in the prompt.
POLL_QUESTION_MAX = 300
POLL_ANSWER_MAX = 55
POLL_MIN_ANSWERS = 2
POLL_MAX_ANSWERS = 10


# Pictures. Jaq is offered the option of attaching one and writes his own
# description of it; this is how that description comes back. The syntax is
# deliberately unlike anything anyone types in a chat window, so a message that
# happens to contain angle brackets is never mistaken for one.
IMAGE_OPEN = "<<image:"
_IMAGE_DIRECTIVE = re.compile(r"<<\s*image\s*:\s*(.*?)\s*>>", re.IGNORECASE | re.DOTALL)
# An unterminated directive, from a reply that hit the token limit mid-sentence.
_IMAGE_TRUNCATED = re.compile(r"<<\s*image\s*:.*$", re.IGNORECASE | re.DOTALL)


def extract_image_prompt(text: str) -> tuple[str, str]:
    """Split a reply into the part that posts and the picture it asked for.

    Runs on every reply, not only the ones where an image was offered. If the
    model produces the directive unprompted - and models reuse a syntax they
    have seen - the visible message must still come out clean, because
    "<<image: a dog>>" appearing in the channel exposes the machinery to
    everyone reading.

    Returns (message, image prompt). The image prompt is "" when there is none.
    """
    if not text or "<<" not in text:
        return text.strip(), ""

    found = _IMAGE_DIRECTIVE.findall(text)
    cleaned = _IMAGE_DIRECTIVE.sub("", text)
    # A directive cut off by the token limit has no closing marker, so the
    # substitution above leaves it in place. Take it out anyway.
    cleaned = _IMAGE_TRUNCATED.sub("", cleaned)

    prompt = next((f.strip() for f in found if f.strip()), "")
    return "\n".join(line.rstrip() for line in cleaned.splitlines()).strip(), prompt


def image_blocked(
    *,
    spent: int,
    cap: int,
    seconds_since_last: float,
    cooldown: float,
) -> str | None:
    """Why the picture path is shut right now, or None if it is open.

    Two independent limits. The daily cap is the money; the cooldown is the
    manners, and it exists because a cap alone lets one back-and-forth with one
    person spend the entire day in ten minutes.

    Returns a reason rather than a bool so the log says which limit bit, which
    is what makes either of them tunable from observed behaviour instead of
    guessed at again.
    """
    if cap and spent >= cap:
        return f"daily cap reached ({spent}/{cap})"
    if cooldown and seconds_since_last < cooldown:
        return f"cooling down ({cooldown - seconds_since_last:.0f}s left)"
    return None


def parse_poll(text: str) -> tuple[str, list[str]] | None:
    """Pull a question and options out of the model's reply.

    Returns None if the shape is wrong or anything breaks Discord's limits, so
    a malformed poll degrades into an ordinary message rather than a rejected
    send.
    """
    question = ""
    answers: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("q:"):
            question = line[2:].strip()
        elif line.startswith(("-", "*")):
            answer = line[1:].strip()
            if answer:
                answers.append(answer)

    if not question or len(question) > POLL_QUESTION_MAX:
        return None
    if not POLL_MIN_ANSWERS <= len(answers) <= POLL_MAX_ANSWERS:
        return None
    if any(not a or len(a) > POLL_ANSWER_MAX for a in answers):
        return None
    return question, answers
