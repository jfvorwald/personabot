"""Context about the people here, read from somewhere that is not this repo.

jaq is public. What jaq knows about actual people cannot be, so it lives in a
separate private checkout and is pointed at from the environment. This module
is the seam: it knows how to read that checkout and nothing about who is in it.

Two shapes are supported, and which one is in use is decided once at import.

    JAQ_PERSONNEL_PATH   a checkout of `personnel` - general/ plus people/<slug>/,
                         with general/people.yml mapping Discord ids to slugs
    JAQ_CONTEXT_PATH     a plain markdown file or a flat directory of them,
                         no structure required and no per-person anything

The second exists so somebody running their own jaq has a way in that does not
involve adopting a private repo's layout. The first is what Jack runs. Neither
being set is a supported state, not an error - the bot came before this did and
still works without it.

Nothing here is allowed to break a reply. A missing checkout, an unparseable
manifest, a file that will not read: each logs and yields nothing, in the same
way a missing image key makes pictures quietly stop happening rather than
making messages fail.

Full injection is a decision that expires. The corpus is small now and every
relevant word fits, so all of it goes in the prompt; once it does not, the
thing to change is `_documents`, which is the only place that decides what is
worth reading. Everything either side of it - the resolution order, the
budget, what the caller sees - is written to survive that swap, so retrieval
lands as a new body for one method rather than as a rewrite.
"""

from __future__ import annotations

import logging
import os
import re

from paths import at_root

log = logging.getLogger("personabot.personnel")

GENERAL = "general"
PEOPLE = "people"
MANIFEST = "people.yml"

# Files that document the layout rather than being context. The same names the
# picture contexts skip, for the same reason: a fresh checkout should not start
# by telling the model about its own directory structure. It is the difference
# between a scaffolded repo doing nothing and a scaffolded repo doing something
# wrong, and only one of those is obvious from the channel.
NOT_CONTENT = {"readme.md", "example.md"}

# A slug becomes a path, so it is checked before it is joined to one. A
# manifest line reading "../../.ssh" is a typo at best and must resolve to
# nothing rather than to somewhere.
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# One entry per line: "<id>": <slug>. Deliberately not a YAML parser. This is a
# flat map of digits to slugs, PyYAML is a dependency the bot does not
# otherwise have, and the repo's other hand-written data file - a picture
# context - is parsed by hand for the same reason. The file keeps its .yml
# extension so it stays valid YAML and a real parser can replace this later.
_ENTRY = re.compile(r"""^\s*["']?(\d+)["']?\s*:\s*["']?([^"'#\s]+)["']?\s*(?:#.*)?$""")


def _is_blank_form(text: str) -> bool:
    """Headings and nothing under them. A form nobody has filled in yet.

    Pre-creating a file per person is the useful thing to do - it is what makes
    sitting down to write easy - but an empty one is not context, and a prompt
    told "## Stance" with nothing beneath it has been handed a blank where it
    expected knowledge. Worse, whatever guidance the template carries for the
    author is addressed to the author, and the model is not the author.

    So the file becomes real the moment there is a sentence in it, and until
    then it is treated as absent. Same instinct as skipping readme.md: the
    scaffolding should do nothing rather than something wrong.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or set(stripped) <= {"-", "*", "="}:
            continue
        return False
    return True


def _read(path: str) -> str | None:
    """A file's text, or None. Never raises - unreadable is a kind of absent."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError) as e:
        log.warning("Could not read %s (%s)", path, type(e).__name__)
        return None


def _markdown_under(directory: str) -> list[str]:
    """Every .md below a directory, sorted, deepest paths last.

    Sorted so the prompt is stable between reads: the same corpus must produce
    the same block, or a cached prefix stops being one and the same question
    gets a different answer depending on how the filesystem felt.
    """
    found = []
    try:
        for root, dirs, files in os.walk(directory):
            dirs.sort()
            for name in sorted(files):
                if name.lower().endswith(".md"):
                    found.append(os.path.join(root, name))
    except OSError as e:
        log.warning("Could not list %s (%s)", directory, type(e).__name__)
    return sorted(found)


def _fit(docs: list[tuple[str, str]], budget: int) -> str:
    """As many documents as the budget allows, in order, and say what was cut.

    Reading in order and stopping is the behaviour a person writing these files
    can predict. Dropping "the largest" or "the least relevant" is cleverer and
    means the author cannot tell from looking at the directory what the model
    actually saw.

    The log line matters as much as the truncation. Silent truncation reads
    from the outside exactly like full coverage, which is how you end up
    debugging the model's judgement when the real problem is that it was never
    shown the file.
    """
    kept: list[str] = []
    spent = 0
    for i, (path, text) in enumerate(docs):
        cost = len(text) + 2
        if spent + cost > budget:
            dropped = len(docs) - i
            log.info(
                "Over budget: %d of %d documents not sent (%s...)",
                dropped, len(docs), os.path.basename(path),
            )
            break
        kept.append(text)
        spent += cost
    return "\n\n".join(kept)


class NullProvider:
    """No external context configured. The state jaq shipped in."""

    name = "none"

    def resolve(self, user_id: int) -> str | None:
        return None

    def load_context(self, scope: str, budget: int) -> str | None:
        return None


class MarkdownProvider:
    """A file, or a flat directory of them. The fallback anyone can supply.

    No manifest and no per-person structure, so a person scope finds nothing
    here. That is the honest answer rather than a degraded one: without a way
    to say which file is about whom, guessing from filenames would sooner or
    later hand one person's notes over under another person's name.
    """

    name = "markdown"

    def __init__(self, path: str):
        self.path = path

    def resolve(self, user_id: int) -> str | None:
        return None

    def _documents(self, scope: str) -> list[tuple[str, str]]:
        if scope != GENERAL:
            return []
        if os.path.isfile(self.path):
            text = _read(self.path)
            return [(self.path, text)] if text else []
        docs = []
        try:
            names = sorted(os.listdir(self.path))
        except OSError as e:
            log.warning("Could not list %s (%s)", self.path, type(e).__name__)
            return []
        for name in names:
            if not name.lower().endswith(".md") or name.lower() in NOT_CONTENT:
                continue
            full = os.path.join(self.path, name)
            if not os.path.isfile(full):
                continue
            text = _read(full)
            if text and not _is_blank_form(text):
                docs.append((full, text))
        return docs

    def load_context(self, scope: str, budget: int) -> str | None:
        return _fit(self._documents(scope), budget) or None


class PersonnelProvider:
    """A checkout of `personnel`: general/ plus people/<slug>/.

    Read fresh on every reply rather than cached at startup. These are content,
    like the picture contexts and the brain's profiles, and content that needs
    a restart to take effect is content nobody edits.
    """

    name = "personnel"

    def __init__(self, root: str):
        self.root = root

    # --- person resolution -------------------------------------------------

    def _manifest(self) -> dict[str, str]:
        """Discord id -> slug, from general/people.yml.

        Forgiving in the same way the picture contexts are: a line that does
        not parse is skipped with a warning rather than taking down the file,
        because this is hand-written by someone adding a person, not generated.
        """
        text = _read(os.path.join(self.root, GENERAL, MANIFEST))
        if text is None:
            return {}
        mapping: dict[str, str] = {}
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = _ENTRY.match(stripped)
            if not match:
                log.warning("%s line %d is not an id: slug pair; skipped", MANIFEST, number)
                continue
            user_id, slug = match.group(1), match.group(2).lower()
            if not _SLUG.match(slug):
                log.warning("%s line %d has an unusable slug %r; skipped", MANIFEST, number, slug)
                continue
            mapping[user_id] = slug
        return mapping

    def resolve(self, user_id: int) -> str | None:
        """Which person, if any, this Discord account is. None is normal."""
        return self._manifest().get(str(user_id))

    # --- reading -----------------------------------------------------------

    def _directory(self, scope: str) -> str | None:
        if scope == GENERAL:
            return os.path.join(self.root, GENERAL)
        if not _SLUG.match(scope):
            log.warning("Refusing to resolve %r as a person directory", scope)
            return None
        return os.path.join(self.root, PEOPLE, scope)

    def _documents(self, scope: str) -> list[tuple[str, str]]:
        """The documents worth showing the model for this scope.

        Today: all of them. This is the method retrieval replaces - the
        signature is already "which documents, for what scope", so a version
        that searches instead of listing changes nothing above it.
        """
        directory = self._directory(scope)
        if not directory or not os.path.isdir(directory):
            return []
        docs = []
        for path in _markdown_under(directory):
            # The manifest lives in general/ and is data, not prose. It is
            # skipped by extension, but a stray people.md would sail straight
            # into the prompt, so say it out loud.
            name = os.path.basename(path).lower()
            if name == MANIFEST or name in NOT_CONTENT:
                continue
            text = _read(path)
            if text and not _is_blank_form(text):
                docs.append((path, text))
        return docs

    def load_context(self, scope: str, budget: int) -> str | None:
        return _fit(self._documents(scope), budget) or None


# --- resolution order ------------------------------------------------------


def _resolve_provider():
    """Personnel if it is there, else plain markdown, else nothing.

    A configured-but-missing path warns and falls through rather than raising.
    Getting this wrong should cost the context, not the bot - the path breaks
    the day the checkout moves, and that is not a reason to stop replying.
    """
    from config import JAQ_CONTEXT_PATH, JAQ_PERSONNEL_PATH

    if JAQ_PERSONNEL_PATH:
        root = JAQ_PERSONNEL_PATH
        if not os.path.isabs(root):
            root = at_root(root)
        if os.path.isdir(root):
            return PersonnelProvider(root)
        log.warning("JAQ_PERSONNEL_PATH is not a directory: %s", root)

    if JAQ_CONTEXT_PATH:
        path = JAQ_CONTEXT_PATH
        if not os.path.isabs(path):
            path = at_root(path)
        if os.path.exists(path):
            return MarkdownProvider(path)
        log.warning("JAQ_CONTEXT_PATH does not exist: %s", path)

    return NullProvider()


_provider = None


def provider():
    """The chosen provider, worked out once."""
    global _provider
    if _provider is None:
        _provider = _resolve_provider()
    return _provider


def describe() -> str:
    """One line for the startup banner, so which source is live is visible."""
    active = provider()
    if isinstance(active, NullProvider):
        return "none"
    return f"{active.name} ({getattr(active, 'root', None) or getattr(active, 'path', '')})"


# --- used by bot.py --------------------------------------------------------


def load_context(scope: str, budget: int | None = None) -> str | None:
    """The interface the task is written against. One scope, one string.

    `scope` is either "general" or a person slug. bot.py does not call this
    directly - it calls load_for below - but this is the seam anything else
    should go through, and it is what keeps the provider swappable.
    """
    from config import CONTEXT_MAX_CHARS

    return provider().load_context(
        scope, CONTEXT_MAX_CHARS if budget is None else budget
    )


def load_for(user_ids: set[int]) -> str:
    """General context plus whoever is in this conversation, as one block.

    Shaped exactly like brain.load_for and appended in the same place, so there
    is one path per-person material takes into a prompt rather than two that
    have to be kept in agreement.

    The budget is spent general-first. General is the material that applies to
    every reply, and a conversation with four people in it should not be able
    to push the group's own shared history out of the prompt.
    """
    from config import CONTEXT_MAX_CHARS
    from prompts import PERSONNEL_HEADER

    active = provider()
    if isinstance(active, NullProvider):
        return ""

    budget = CONTEXT_MAX_CHARS
    blocks: list[str] = []

    general = active.load_context(GENERAL, budget)
    if general:
        blocks.append(general)
        budget -= len(general)

    # Sorted so the same set of speakers always produces the same prompt.
    for user_id in sorted(user_ids):
        if budget <= 0:
            log.info("Budget spent before people; %d speakers not loaded", len(user_ids))
            break
        slug = active.resolve(user_id)
        if not slug:
            continue
        text = active.load_context(slug, budget)
        if not text:
            continue
        blocks.append(f"### {slug}\n\n{text}")
        budget -= len(text)

    if not blocks:
        return ""
    return f"{PERSONNEL_HEADER}\n\n" + "\n\n".join(blocks)
