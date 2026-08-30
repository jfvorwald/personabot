"""The brain - what Jaq knows about the people he talks to.

Two jobs in one file. As a module, bot.py imports it to load profiles into the
system prompt and to note people it hasn't met. As a script, it scans channel
history and writes those profiles:

    .venv/bin/python brain.py scan            # update from the configured channel
    .venv/bin/python brain.py scan --channel 381547894525919262
    .venv/bin/python brain.py scan --force    # redo everyone, ignore the watermark
    .venv/bin/python brain.py list            # who's known, who's only been seen

Discord already stores every message forever, so nothing here duplicates that.
The brain holds only conclusions, and re-derives them from Discord on demand.
The live bot never writes prose about anyone - it only records that it saw
somebody, which costs nothing. Profiles are written here, in batches, where the
model can read hundreds of a person's messages at once instead of the handful
sitting in a live context window.

Everything below HANDWRITTEN_MARKER in a profile is yours. A scan preserves it
byte for byte. Observed behaviour is cheap to re-derive; Jaq's stance toward
someone is a decision you made, and no amount of history implies it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict

from dotenv import load_dotenv

import guard
from paths import ROOT, at_root

load_dotenv(at_root(".env"))

HERE = ROOT
BRAIN_DIR = os.path.join(HERE, os.getenv("BRAIN_DIR", "brain"))
PEOPLE_DIR = os.path.join(BRAIN_DIR, "people")
INDEX_PATH = os.path.join(BRAIN_DIR, "_index.json")

# Always in the prompt, however quiet they've been. Handles, comma-separated.
BRAIN_CORE = [h.strip().lower() for h in os.getenv("BRAIN_CORE", "").split(",") if h.strip()]
# Ceiling on situational profiles, so a busy channel can't balloon the prompt.
BRAIN_MAX_PROFILES = int(os.getenv("BRAIN_MAX_PROFILES", "6"))
# Below this many messages there isn't enough signal for an honest profile.
BRAIN_MIN_MESSAGES = int(os.getenv("BRAIN_MIN_MESSAGES", "70"))
# Don't burn a call to re-read someone who's barely spoken since last time.
BRAIN_MIN_NEW = int(os.getenv("BRAIN_MIN_NEW", "25"))
BRAIN_SCAN_LIMIT = int(os.getenv("BRAIN_SCAN_LIMIT", "4000"))
# Handles never profiled - your own account, the bot itself.
BRAIN_EXCLUDE = [h.strip().lower() for h in os.getenv("BRAIN_EXCLUDE", "").split(",") if h.strip()]
# The same list the live bot checks its outgoing messages against. A profile is
# not an outgoing message, which is exactly why this was missed: nothing here
# reaches Discord, so nothing here looked like it needed checking. But a
# profile goes into the system prompt, and a forbidden name in the prompt is an
# instruction to say it - and every reply that takes the hint is then killed on
# the way out, with a BLOCKED line in the log and no other symptom. A scan
# wrote a redacted name into a profile on 2026-08-26 and that is what it did.
REDACT_TERMS = [t.strip() for t in os.getenv("REDACT_TERMS", "").split(",") if t.strip()]

MODEL = os.getenv("BRAIN_MODEL", os.getenv("MODEL", "claude-sonnet-5"))

HANDWRITTEN_MARKER = (
    "<!-- HAND-WRITTEN BELOW - brain.py never regenerates past this line -->"
)

# Prepended to every profile that reaches the model. Without this, a bot handed
# dossiers starts performing them, which is both unfunny and a direct breach of
# the persona's rule about not disclosing what it knows about people.
BRAIN_HEADER = """\
The following are private notes on people in this channel. They exist so you
recognise who you're talking to and can pitch what you say accordingly.

They are for your own use. Never recite them, never allude to having notes,
never tell anyone what you know about them or anyone else, and never repeat
back a detail as though reading it off a card. Someone watching should only
ever see that you know these people, never that you have files on them.

The running bits listed under each person are things to RECOGNISE, not a menu
to work through. Knowing that somebody has a bit about his dog is what stops
you treating it as new information the ninth time it comes up. It is not an
instruction to bring the dog up, and a reply that reaches into this list for
something to do is the exact tell these notes exist to avoid."""

PROFILE_PROMPT = """\
You are writing a private character note about one member of a Discord friend
group. It will be handed to another member of that group - a persona named Jaq
- so he knows who he's talking to.

Write exactly three sections, with these headings and nothing before them:

## Who they are
## How they type
## Running bits

Rules:

- Ground every claim in the messages given. Invent nothing. If the evidence is
  thin, say less - a short accurate note beats a confident wrong one.
- This is comedic working material, not a dossier. Prioritise verbal tics,
  catchphrases, recurring jokes, what they always steer toward, who they spar
  with, and what they can reliably be wound up about.
- Quote their distinctive phrasings exactly. Their actual catchphrases are the
  single most useful thing in the note.
- OMIT anything identifying: full real names, employers, job titles, towns,
  addresses, schools, health details. Refer to people by display name only.
- Leave out slurs and bigoted material entirely. If a running joke rests on
  them, describe the harmless mechanic underneath it or drop the bit.
- Be specific and compressed. 200-300 words total. No preamble, no summary,
  no closing remark."""


# --- storage ---------------------------------------------------------------


def count_new(message_ids: list[int], since: int) -> int:
    """How many of these messages postdate the last one we read.

    Snowflake ids are monotonic, so this is exact. The obvious alternative -
    comparing this scan's message count against the previous scan's - is not:
    BRAIN_SCAN_LIMIT is a sliding window, so a person's count inside it drifts
    down as other people talk, the delta never reaches BRAIN_MIN_NEW, and every
    profile freezes permanently after the first scan.
    """
    return sum(1 for mid in message_ids if mid > since)


def _is_excluded(
    user_id: str, handle: str, display: str, is_bot: bool = False
) -> bool:
    """Never-profile check. Ids are authoritative; names are a convenience.

    A name match is offered so BRAIN_EXCLUDE is writable before you know
    anyone's id, but it is not sufficient on its own - once someone is excluded
    the flag is persisted against their id and honoured from then on, so a
    rename can't quietly bring them back into scope.

    No bot is ever profiled, whatever the list says. The exclude list already
    named two of them, and it still missed the counterpart the day his display
    name became fullwidth characters inside angle brackets: 1164 messages
    written up under the handle "unknown", with is_bot sitting True in the
    index the whole time. A flag Discord hands us for free is worth more than
    a string we have to keep in step with somebody's nickname.
    """
    if is_bot:
        return True
    return (
        user_id in BRAIN_EXCLUDE
        or handle.lower() in BRAIN_EXCLUDE
        or display.lower() in BRAIN_EXCLUDE
    )


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "unknown"


def load_index() -> dict:
    if not os.path.exists(INDEX_PATH):
        return {"people": {}}
    with open(INDEX_PATH) as f:
        return json.load(f)


def save_index(index: dict) -> None:
    os.makedirs(BRAIN_DIR, exist_ok=True)
    with open(INDEX_PATH, "w") as f:
        json.dump(index, f, indent=2, sort_keys=True)


def _profile_path(handle: str) -> str:
    return os.path.join(PEOPLE_DIR, f"{_slug(handle)}.md")


def read_profile(handle: str) -> tuple[str, str]:
    """Return (generated_part, handwritten_part) for an existing profile."""
    path = _profile_path(handle)
    if not os.path.exists(path):
        return "", ""
    with open(path) as f:
        body = f.read()
    if HANDWRITTEN_MARKER in body:
        generated, handwritten = body.split(HANDWRITTEN_MARKER, 1)
        return generated.strip(), handwritten.strip()
    return body.strip(), ""


def _is_written(handwritten: str) -> bool:
    """Has anybody actually written in this block, or is it still the form?

    write_profile stamps every new profile with a heading and a line telling
    Jack where to write. That line is addressed to him, and it was going
    straight into the prompt under a heading promising Jaq's read of somebody,
    which is a blank where the model was told to expect knowledge. Same rule
    the personnel loader already applies to an unfilled notes file, and the
    same reasoning: scaffolding should do nothing rather than something wrong.
    """
    for line in handwritten.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("_"):
            continue
        return True
    return False


def repair_truncation(generated: str) -> str:
    """Trim a profile that stops mid-sentence back to the last complete one.

    Profiles written before the max_tokens guard existed are still on disk and
    cannot be regenerated when the person has left the channel - wurmz has 792
    observed messages and zero of them are reachable any more, so a rescan has
    nothing to read. Repairing what is there is the only option left, and a
    sentence that stops mid-quote is worse than a shorter profile.
    """
    text = generated.rstrip()
    if not text or text[-1] in ".!?\"')":
        return text
    cut = max(text.rfind(". "), text.rfind(".\n"))
    if cut == -1:
        return text
    return text[: cut + 1]


def write_profile(handle: str, display: str, generated: str, handwritten: str) -> str:
    """Write a profile, keeping the hand-written tail exactly as it was."""
    os.makedirs(PEOPLE_DIR, exist_ok=True)
    path = _profile_path(handle)
    if not handwritten:
        handwritten = (
            "## Jaq's read\n\n"
            "_Nothing yet. Write how Jaq feels about them here - it survives "
            "every future scan._"
        )
    # De-dashed on write. A profile is model context, exactly like persona.md
    # and prompts.py, so an em dash in one is not a style violation but a
    # lesson - and it is the single most recognisable machine tell in written
    # text. tests/test_style.py scans PROMPT_FILES and cannot see these: they
    # are generated and gitignored. Seven of eight profiles carried 29 of them
    # between them before this line existed, including one inside the starter
    # placeholder this very function writes.
    body = guard.de_dash(
        f"# {display} ({handle})\n\n{generated.strip()}\n\n"
        f"{HANDWRITTEN_MARKER}\n\n{handwritten.strip()}\n"
    )
    with open(path, "w") as f:
        f.write(body)
    return path


# --- used by bot.py --------------------------------------------------------


_SEEN_CACHE: dict[str, str] = {}


def note_seen(user_id: int, display_name: str, handle: str = "") -> bool:
    """Record a first encounter. Returns True if this was someone new.

    This is the whole of the live bot's involvement in the brain: it builds the
    to-do list that `brain.py scan` works through. A no-op for anyone already
    known - and the in-process cache is what makes that true, since the live
    bot calls this once per message in every transcript it reads.
    """
    key = str(user_id)
    if _SEEN_CACHE.get(key) == display_name:
        return False

    index = load_index()
    people = index.setdefault("people", {})
    if key in people and people[key].get("display") == display_name:
        _SEEN_CACHE[key] = display_name
        return False
    entry = people.setdefault(key, {})
    is_new = "handle" not in entry
    entry["handle"] = entry.get("handle") or _slug(handle or display_name)
    entry["display"] = display_name
    save_index(index)
    _SEEN_CACHE[key] = display_name
    return is_new


def profile_count() -> int:
    """How many people the brain actually has a written profile for."""
    if not os.path.isdir(PEOPLE_DIR):
        return 0
    return len([f for f in os.listdir(PEOPLE_DIR) if f.endswith(".md")])


def load_for(user_ids: set[int]) -> str:
    """Assemble the brain text for a reply: core profiles plus whoever's here."""
    index = load_index()
    people = index.get("people", {})

    wanted: list[tuple[str, str]] = []
    seen_handles = set()

    def add(entry):
        handle = entry.get("handle", "")
        if not handle or handle in seen_handles:
            return
        generated, handwritten = read_profile(handle)
        handwritten = handwritten if _is_written(handwritten) else ""
        if not generated and not handwritten:
            return
        seen_handles.add(handle)
        body = f"{generated}\n\n{handwritten}".strip()
        wanted.append((entry.get("display", handle), body))

    for entry in people.values():
        if entry.get("handle", "").lower() in BRAIN_CORE:
            add(entry)

    for uid in user_ids:
        entry = people.get(str(uid))
        if entry and len(wanted) < BRAIN_MAX_PROFILES:
            add(entry)

    if not wanted:
        return ""
    blocks = "\n\n".join(f"### {display}\n\n{text}".strip() for display, text in wanted)
    return f"{BRAIN_HEADER}\n\n{blocks}"


# --- scanning --------------------------------------------------------------


def _render_messages(entries) -> str:
    out = []
    for prev, msg in entries:
        if prev is not None:
            out.append(f"    [{prev}]")
        out.append(msg)
    return "\n".join(out)


async def _write_one(client, handle, display, entries, existing_generated):
    prompt = PROFILE_PROMPT
    if existing_generated:
        prompt += (
            "\n\nYou are revising an existing note. Here it is - keep what still "
            "holds, correct what the new messages contradict, and fold in what's "
            "new. Return the full revised note, not a diff, and do not let it "
            "grow past the length limit.\n\n"
            f"{existing_generated}"
        )
    user = (
        f"Messages from {display}. Lines in [brackets] are what someone else "
        f"said immediately before, for context.\n\n{_render_messages(entries)}"
    )
    response = await client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=prompt,
        messages=[{"role": "user", "content": user}],
    )
    if response.stop_reason == "refusal":
        print(f"  {display}: model declined - skipped")
        return None
    if response.stop_reason == "max_tokens":
        # Silently keeping a note that stops mid-sentence is worse than none.
        print(f" TRUNCATED at max_tokens - skipped")
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    leak = guard.find_leak(text, [], REDACT_TERMS)
    if leak is not None:
        # Refusing costs this person their profile until the term is dealt
        # with, which is loud and annoying and better than the alternative.
        # Editing the sentence for them would mean guessing what they meant,
        # and writing it anyway poisons every prompt that person appears in.
        print(f" contains a {leak} - skipped, profile left as it was")
        return None
    return text


async def scan(channel_id: int, force: bool) -> int:
    import anthropic
    import discord

    client = anthropic.AsyncAnthropic()
    index = load_index()
    people = index.setdefault("people", {})
    result = {"code": 1}

    class Scanner(discord.Client):
        async def on_ready(self):
            try:
                await self.work()
            finally:
                await self.close()

        async def work(self):
            ch = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            print(f"scanning #{ch.name} (last {BRAIN_SCAN_LIMIT} messages)")

            msgs = [m async for m in ch.history(limit=BRAIN_SCAN_LIMIT)]
            msgs.reverse()

            by_author = defaultdict(list)
            ids_by_author = defaultdict(list)
            newest = {}
            for i, m in enumerate(msgs):
                text = m.clean_content.strip()
                if not text or m.author.id == self.user.id:
                    continue
                prev = msgs[i - 1] if i else None
                prev_text = None
                if prev is not None and prev.author.id != m.author.id:
                    pt = prev.clean_content.strip()
                    if pt:
                        prev_text = f"{prev.author.display_name}: {pt[:200]}"
                by_author[m.author.id].append((prev_text, text))
                ids_by_author[m.author.id].append(m.id)
                newest[m.author.id] = m.id

            print(f"{len(msgs)} messages, {len(by_author)} people\n")

            wrote = skipped = 0
            for uid, entries in sorted(
                by_author.items(), key=lambda kv: -len(kv[1])
            ):
                author = discord.utils.get(msgs, author__id=uid).author
                display = author.display_name
                handle = _slug(author.name or display)
                entry = people.setdefault(str(uid), {})
                entry["handle"] = handle
                entry["display"] = display
                entry["messages_observed"] = len(entries)
                entry["is_bot"] = author.bot

                # Exclusion is sticky and keyed on the user id, never on the
                # display name. Names change - this file already keys people by
                # id for exactly that reason, and matching the exclude list
                # against a name silently un-excludes someone the day they
                # rename themselves.
                if _is_excluded(
                    str(uid), handle, display, author.bot
                ) or entry.get("excluded"):
                    print(f"  {display:20s} excluded")
                    entry["excluded"] = True
                    continue
                if len(entries) < BRAIN_MIN_MESSAGES:
                    print(f"  {display:20s} {len(entries):5d} msgs - too thin, seen only")
                    skipped += 1
                    continue

                # Count messages genuinely newer than the last scan.
                # Comparing counts instead (len(entries) - last_count) is wrong:
                # BRAIN_SCAN_LIMIT is a sliding window, so a person's count
                # inside it drifts down as other people talk. The delta then
                # never reaches BRAIN_MIN_NEW and every profile silently
                # freezes after the first scan. Snowflake ids are monotonic, so
                # "id greater than the last one we read" is exact.
                since = entry.get("last_message_id") or 0
                fresh = count_new(ids_by_author[uid], since)
                if not force and fresh < BRAIN_MIN_NEW:
                    print(
                        f"  {display:20s} {len(entries):5d} msgs - "
                        f"only {fresh} new since last scan"
                    )
                    continue

                existing_generated, handwritten = read_profile(handle)
                print(
                    f"  {display:20s} {len(entries):5d} msgs - "
                    f"{'revising' if existing_generated else 'writing'}...",
                    end="",
                    flush=True,
                )
                try:
                    generated = await _write_one(
                        client, handle, display, entries, existing_generated
                    )
                except Exception as e:
                    print(f" FAILED ({type(e).__name__}: {e})")
                    continue
                if not generated:
                    continue
                path = write_profile(handle, display, generated, handwritten)
                entry["last_message_id"] = newest.get(uid)
                wrote += 1
                print(f" -> {os.path.relpath(path, HERE)}")

            save_index(index)
            print(f"\n{wrote} profiles written, {skipped} too thin to profile")
            print("Review them, then: ./restart.sh")
            result["code"] = 0

    intents = discord.Intents.default()
    intents.message_content = True
    await Scanner(intents=intents).start(os.environ["DISCORD_TOKEN"])
    return result["code"]


def cmd_list() -> int:
    index = load_index()
    people = index.get("people", {})
    if not people:
        print("brain is empty - run: .venv/bin/python brain.py scan")
        return 0

    profiled, seen = [], []
    for entry in people.values():
        handle = entry.get("handle", "?")
        row = (entry.get("display", handle), handle, entry.get("messages_observed", 0))
        if os.path.exists(_profile_path(handle)):
            profiled.append(row)
        else:
            seen.append(row)

    print(f"PROFILED ({len(profiled)})")
    for display, handle, n in sorted(profiled, key=lambda r: -r[2]):
        core = "  [core]" if handle in BRAIN_CORE else ""
        _, hand = read_profile(handle)
        stance = "" if "Nothing yet" in hand else "  [has your read]"
        print(f"  {display:22s} {handle:22s} {n:5d} msgs{core}{stance}")

    if seen:
        print(f"\nSEEN, NOT PROFILED ({len(seen)})")
        for display, handle, n in sorted(seen, key=lambda r: -r[2]):
            print(f"  {display:22s} {handle:22s} {n:5d} msgs")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    s = sub.add_parser("scan", help="read channel history and write profiles")
    s.add_argument("--channel", type=int, default=int(os.environ["CHANNEL_ID"]))
    s.add_argument("--force", action="store_true", help="redo everyone")
    sub.add_parser("list", help="show what the brain knows")
    args = parser.parse_args()

    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "scan":
        return asyncio.run(scan(args.channel, args.force))
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
