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


def within_hours(hour: int, start: int, end: int) -> bool:
    """True if a local hour falls in the half-open window [start, end).

    Wraps past midnight when start > end, so 22-6 means late evening through
    early morning rather than nothing at all. start == end is the whole day:
    a window nobody narrowed should not silently switch the feature off.
    """
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


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


# A direct order from the creator. Matched as a standalone word so it cannot
# fire inside "obeying" or "disobey", and required to be shouted, because a
# word that also appears in ordinary speech is a bad trigger for something
# this absolute. Only one person can use it, checked separately.
_OBEY = re.compile(r"(?:^|[^A-Za-z])OBEY(?![A-Za-z])")


def is_obey_order(text: str) -> bool:
    """Is this an order rather than a message?

    Case-sensitive on purpose. "obey" turns up in ordinary sentences - "I obey
    nobody", "he'd never obey that" - and this is not a thing that should fire
    by accident. Shouting it is the signal.
    """
    return bool(text) and bool(_OBEY.search(text))


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


# Asking for a picture. Broader than ART_VERBS on purpose: that list was built
# for ASCII art and does not know the words "create" or "generate", which is
# how "create a picture of X" walked straight past it and got exactly the
# picture the asker specified.
PICTURE_NOUNS = {
    "picture", "pictures", "pic", "pics", "image", "images", "img", "photo",
    "photos", "photograph", "drawing", "artwork", "render", "meme", "selfie",
    "portrait", "art", "painting", "illustration",
}
PICTURE_VERBS = {
    "create", "generate", "make", "render", "draw", "sketch", "paint",
    "produce", "design", "post", "send", "show", "give", "gimme", "do",
}


# Phrasings that mean "draw this" without naming a picture at all. Jack asks
# this way constantly and it matched nothing: no verb from the list, no noun
# from the list. Handled here rather than left to the classifier so it is
# deterministic - a phrase he uses on purpose should not depend on a model
# agreeing with him about it.
PICTURE_PHRASES = (
    "imagine yourself", "imagine you as", "imagine you in", "imagine you're",
    "imagine youre", "imagine us", "picture yourself", "picture this",
    "what would it look like", "what would that look like",
    "what would you look like", "i want to see", "let me see",
)


def is_picture_request(text: str) -> bool:
    """Is someone asking for a picture?

    Nobody is allowed to commission one, so this exists to shut the door
    rather than to open it: a message that matches means the option is never
    offered on that reply. The verb has to be in imperative position, the same
    test is_art_request uses - "make a picture" is an order, "the picture" is
    a noun phrase.
    """
    lowered = text.strip().lower()
    if not lowered:
        return False
    if any(phrase in lowered for phrase in PICTURE_PHRASES):
        return True
    words = [w.strip("?!.,:;\"'") for w in lowered.split()]
    blockers = WH_WORDS | AUXILIARIES | {
        "someone", "anyone", "if", "that", "the", "this", "these", "those",
        "my", "your", "his", "her", "their", "our",
    }
    for i, word in enumerate(words):
        if word in PICTURE_VERBS:
            if set(words[:i]) & blockers:
                return False
            return bool(set(words[i + 1:]) & PICTURE_NOUNS)
    return False


# Deliverables people ask for that can be made for real inside a code block.
# Each noun maps to the shape the prompt should build. Narrow on purpose, the
# same way ART_NOUNS is: this fires a whole bit, so a word that merely appears
# in a sentence about work must not trigger one. "summary", "list" and "notes"
# were all considered and left out - people ask for those meaning "tell me",
# and answering in words is the correct reply to that.
ARTIFACT_NOUNS = {
    "spreadsheet": "spreadsheet", "spreadsheets": "spreadsheet",
    "excel": "spreadsheet", "xlsx": "spreadsheet", "csv": "spreadsheet",
    "table": "spreadsheet", "sheet": "spreadsheet",
    "deck": "deck", "slides": "deck", "slide": "deck",
    "powerpoint": "deck", "presentation": "deck", "keynote": "deck",
    "gantt": "gantt", "roadmap": "gantt", "timeline": "gantt",
    "orgchart": "org chart", "hierarchy": "org chart",
    "invoice": "invoice", "receipt": "invoice", "quote": "invoice",
    "bill": "invoice",
    "budget": "budget", "forecast": "budget", "projections": "budget",
    "p&l": "budget",
    "form": "form", "survey": "form", "questionnaire": "form",
    "resume": "resume", "cv": "resume",
    "contract": "contract", "nda": "contract", "agreement": "contract",
    "schedule": "schedule", "roster": "schedule", "rota": "schedule",
    "itinerary": "schedule", "agenda": "schedule",
    "tierlist": "tier list", "leaderboard": "tier list",
    "scoreboard": "tier list", "bracket": "tier list",
    "flowchart": "flowchart", "wireframe": "flowchart",
    "certificate": "certificate", "award": "certificate",
    "menu": "menu",
}

# Two-word names, checked as substrings before the word scan because splitting
# on whitespace loses them.
ARTIFACT_PHRASES = {
    "spread sheet": "spreadsheet", "pivot table": "spreadsheet",
    "org chart": "org chart", "tier list": "tier list",
    "slide deck": "deck", "pitch deck": "deck",
    "gantt chart": "gantt", "flow chart": "flowchart",
    "balance sheet": "budget", "purchase order": "invoice",
    "performance review": "form", "incident report": "form",
}

ARTIFACT_VERBS = {
    "make", "build", "create", "generate", "draft", "prepare", "write",
    "produce", "compile", "assemble", "give", "gimme", "send", "show",
    "whip", "cook", "throw", "put", "knock", "spin",
}


def wants_artifact(text: str) -> str | None:
    """Which deliverable someone is asking for, if any.

    Returns the shape to build - "spreadsheet", "deck", "invoice" - or None.
    The verb has to be in imperative position, the same test is_art_request
    and is_picture_request use: "build a spreadsheet" is an order, "the
    spreadsheet is wrong" and "can anyone read this spreadsheet" are not.

    Callers must check the ASCII art path first. "chart" and "diagram" belong
    to that one, and the older surface does not get to quietly lose words to
    the newer one.
    """
    lowered = text.strip().lower()
    if not lowered:
        return None
    words = [w.strip("?!.,:;\"'") for w in lowered.split()]
    if not words:
        return None

    blockers = WH_WORDS | AUXILIARIES | {
        "someone", "anyone", "somebody", "anybody", "if", "that", "the",
        "a", "an", "this", "these", "those", "my", "your", "his", "her",
        "their", "our", "its",
    }
    for i, word in enumerate(words):
        if word not in ARTIFACT_VERBS:
            continue
        if set(words[:i]) & blockers:
            return None
        rest = lowered.split(word, 1)[1]
        for phrase, shape in ARTIFACT_PHRASES.items():
            if phrase in rest:
                return shape
        for later in words[i + 1:]:
            if later in ARTIFACT_NOUNS:
                return ARTIFACT_NOUNS[later]
        return None
    return None


def wants_ascii(text: str) -> bool:
    """Did they specifically ask for ASCII, rather than for a picture?

    There are two drawing surfaces now - characters in a code fence, and a real
    render. Asking for one by name has to still get that one, or the older
    feature quietly disappears the day the newer one arrives.
    """
    return "ascii" in {w.strip("?!.,:;\"'") for w in text.lower().split()}


def mentions_a_picture(text: str) -> bool:
    """Does this message talk about pictures at all?

    Deliberately blunter than is_picture_request, and used for the same
    purpose: to withhold the option. A request phrased in a way no wordlist
    anticipated still almost always names the thing it wants, and
    over-suppressing costs nothing here because pictures are meant to arrive
    when nobody was angling for one.
    """
    lowered = text.strip().lower()
    if not lowered:
        return False
    return bool({w.strip("?!.,:;\"'") for w in lowered.split()} & PICTURE_NOUNS)


# Words too common to say anything about whether two texts describe the same
# thing. Kept small - this is a similarity check, not a search engine.
_STOPWORDS = {
    "the", "a", "an", "and", "but", "or", "of", "in", "on", "at", "to", "for",
    "with", "from", "into", "over", "under", "like", "its", "it's", "that",
    "this", "some", "something", "someone", "one", "all", "just", "very",
    "still", "been", "being", "have", "has", "had", "was", "were", "are",
    "is", "be", "not", "no", "you", "your", "his", "her", "their", "them",
}


def _content_words(text: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9\s-]", " ", text.lower())
    return {w for w in cleaned.split() if len(w) > 2 and w not in _STOPWORDS}


def looks_like_a_caption(message: str, prompt: str, threshold: float = 0.5) -> bool:
    """Is the message just a description of the picture it came with?

    The failure this catches, seen in the channel: asked for a picture, Jaq
    posted "a robot made of forehead-kiss residue and a permanent -58 balance,
    rendered in the exact lighting of..." - art direction read aloud, not
    something a person says. The instruction not to caption was already in the
    prompt and did not hold, which is why this is a measurement instead.

    Compares against the picture's own prompt rather than judging the sentence
    on its own, so an ordinary message that happens to describe something is
    left alone.
    """
    words = _content_words(message)
    described = _content_words(prompt)
    if not words or not described:
        return False
    return len(words & described) / len(words) >= threshold


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


# "*[image attached]*", "*picture attached*", "(image)". The prompt forbids
# announcing the picture and the model does it anyway, so this is the version
# that holds. Deliberately narrow: it needs an attach-ish word inside a
# bracket, asterisk or paren wrapper, or a whole line that is nothing else.
_ATTACH_SPAN = re.compile(
    r"[\*_\[\(]+[^\]\)\*_\n]{0,40}?(?:attach\w*|image|picture|pic|photo)"
    r"[^\]\)\*_\n]{0,40}?[\*_\]\)]+",
    re.IGNORECASE,
)
_ATTACH_LINE = re.compile(
    r"^\W*(?:image|picture|pic|photo)\s+attach\w*\W*$|"
    r"^\W*attach\w*\s*:?\s*(?:image|picture|pic|photo)?\W*$",
    re.IGNORECASE,
)


def strip_attachment_notes(text: str) -> str:
    """Remove the model announcing its own attachment.

    A picture arriving needs no narration - Discord shows it. "*[image
    attached]*" above a real image reads as a bot describing its own output,
    and above a failed one it is a promise of something that never comes.
    """
    if not text:
        return text
    kept = []
    for line in text.splitlines():
        if _ATTACH_LINE.match(line.strip()):
            continue
        cleaned = _ATTACH_SPAN.sub("", line) if "attach" in line.lower() else line
        kept.append(cleaned.rstrip())
    # Collapse the blank line the removal usually leaves behind.
    out = "\n".join(kept)
    return re.sub(r"\n{2,}", "\n\n", out).strip()


# Discord's reply feature, requested by the model rather than decided in code:
# whether a line is a burn that needs its target attached is a judgement, and a
# dice roll would fire it on ordinary remarks while suppressing the real ones.
_REPLY_FLAG = re.compile(r"<<\s*reply\s*>>", re.IGNORECASE)


# A free pre-filter for the help check. The classification call is what decides;
# this only avoids paying for it on messages that are plainly not a problem.
# Deliberately loose - a false positive costs one cheap call, and a false
# negative costs someone a real answer.
TROUBLE_WORDS = {
    "broken", "broke", "breaking", "error", "errors", "fails", "failing",
    "failed", "crash", "crashes", "crashing", "bug", "bugged", "stuck",
    "wrong", "issue", "problem", "help", "why", "how", "cant", "can't",
    "cannot", "wont", "won't", "doesnt", "doesn't", "isnt", "isn't", "not",
    "fix", "fixed", "install", "installed", "update", "updated", "setup",
    "config", "settings", "keeps", "again", "anyone", "supposed", "tried",
    "trying", "lag", "lagging", "disconnect", "disconnected", "timeout",
    "slow", "missing", "lost", "reset", "recover", "corrupt", "corrupted",
    # Not being stuck, but not understanding. Built the first version around
    # broken things and missed every request for an explanation - "what
    # actually is a vpn" reached nothing at all.
    "what", "whats", "explain", "difference", "understand", "mean", "means",
    "meaning", "actually", "even", "point", "versus", "vs", "better", "worth",
    "should", "which", "eli5",
}


def might_need_help(text: str) -> bool:
    """Cheap gate before spending a call on the real judgement.

    Loose on purpose. The expensive check is what decides, and the asymmetry
    matters: a false positive here costs one small classification, a false
    negative costs somebody the answer they needed.
    """
    lowered = text.strip().lower()
    if not lowered or len(lowered.split()) < 3:
        return False
    words = {w.strip("?!.,:;\"'()") for w in lowered.split()}
    return bool(words & TROUBLE_WORDS) or lowered.endswith("?")


def wants_reply_to(text: str) -> tuple[str, bool]:
    """Split a message into what posts and whether to attach it to its target.

    Stripped whether or not the flag was offered, on the same principle as the
    image directive: a model that has seen a syntax will eventually reproduce
    it, and "<<reply>>" appearing in the channel exposes the machinery.
    """
    if not text or "<<" not in text:
        return text, False
    found = bool(_REPLY_FLAG.search(text))
    cleaned = _REPLY_FLAG.sub("", text)
    return "\n".join(line.rstrip() for line in cleaned.splitlines()).strip(), found


_GIF_DIRECTIVE = re.compile(r"<<\s*gif\s*:\s*(.*?)\s*>>", re.IGNORECASE | re.DOTALL)
_GIF_TRUNCATED = re.compile(r"<<\s*gif\s*:.*$", re.IGNORECASE | re.DOTALL)


def extract_gif_terms(text: str) -> tuple[str, int]:
    """Split a reply into what posts and which GIF from the pool was picked.

    A number rather than search terms: the pool is curated, so choosing is
    picking from a list rather than gambling on an index.

    Stripped on every reply rather than only offered ones, for the third time
    on the same principle: a model that has seen a syntax reproduces it, and
    the directive appearing in the channel shows the wiring to everyone.
    """
    if not text or "<<" not in text:
        return text.strip(), 0
    found = _GIF_DIRECTIVE.findall(text)
    cleaned = _GIF_TRUNCATED.sub("", _GIF_DIRECTIVE.sub("", text))
    picked = 0
    for candidate in found:
        digits = re.sub(r"[^0-9]", "", candidate)
        if digits:
            picked = int(digits)
            break
    return "\n".join(line.rstrip() for line in cleaned.splitlines()).strip(), picked


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
