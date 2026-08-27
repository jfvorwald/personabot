"""Every knob, read from the environment in one place.

Split out so the settings can be read end to end without the machinery, and
so nothing else has to call os.getenv. Values are read once at import; the
decision logic in decide.py takes them as arguments rather than importing
them, which is what lets tests exercise it under any configuration.
"""

from __future__ import annotations

import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from paths import at_root

load_dotenv(at_root(".env"))

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
PERSONA_FILE = os.getenv("PERSONA_FILE", "persona.md")
# How conversation works, kept apart from who Jaq is so the two can be
# edited independently. Optional - absent file just means no block.
PSYCHOLOGY_FILE = os.getenv("PSYCHOLOGY_FILE", "psychology.md")
# Words and phrases you want in rotation, comma-separated. Anything Jack
# picks up and wants Jaq using - good, bad, or in-joke. Edited far more
# often than the persona itself, which is why it lives here and not there.
VOCAB = [w.strip() for w in os.getenv("VOCAB", "").split(",") if w.strip()]

# Strings that must never appear in anything the bot posts. The prompt asks
# the model to keep these back; this is the check that runs on the way out,
# for when asking is not enough. Credentials are added automatically.
REDACT_TERMS = [
    t.strip() for t in os.getenv("REDACT_TERMS", "").split(",") if t.strip()
]
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "UTC"))
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "30"))
MODEL = os.getenv("MODEL", "claude-opus-5")
EFFORT = os.getenv("EFFORT", "low")

# --live guards. Two bots that each reply on every message would loop forever,
# so live mode ignores bot authors by default and rations replies per day.
LIVE_REPLY_TO_BOTS = os.getenv("LIVE_REPLY_TO_BOTS", "false").lower() == "true"

# A fresh budget is drawn in this range each day rather than using a fixed
# number - a bot that stops dead on the same count every day is a bot people
# can measure. Only messages actually posted count against it.
#
# Set LIVE_DAILY_MAX=0 for no limit. Note that the budget is the only hard
# stop on two bots replying to each other forever; with it off, the brakes are
# the model's own choice to <pass> and nothing else.
LIVE_DAILY_MIN = int(os.getenv("LIVE_DAILY_MIN", "4"))
LIVE_DAILY_MAX = int(os.getenv("LIVE_DAILY_MAX", "10"))
LIVE_UNLIMITED = LIVE_DAILY_MAX <= 0

# The budget above is a soft one: an @mention from a human and anything an ally
# says are answered past it, because the budget exists to stop two bots looping
# forever and neither of those is that. The effect is that a busy day runs well
# over - 51 replies against a budget of 32 on the day this was added.
#
# This is the ceiling on that overage, as a multiple of the day's budget, and
# nothing crosses it. A friend who has already had three times a full day of
# replies is not being blanked; the day is simply over.
LIVE_HARD_CAP_MULTIPLIER = float(os.getenv("LIVE_HARD_CAP_MULTIPLIER", "3"))

# What any single person can spend in a day. The caps above are shared, so
# without this one person in a long back-and-forth drains the day and everyone
# else finds a bot that has nothing left for them - the loudest person in the
# room deciding how much of it everyone else gets.
#
# Allies are exempt from this and from the hard cap. Jack owns the thing; he is
# not queueing behind a quota to talk to it. 0 disables it.
LIVE_PER_PERSON_MAX = int(os.getenv("LIVE_PER_PERSON_MAX", "12"))

# Counterpart bots: matched case-insensitively against the Discord display
# name. These bypass the ignore-other-bots rule so the two personas can talk at
# all - but they are NOT guaranteed a reply. Letting one sit unanswered is
# allowed, and everything still spends from the daily budget, which is what
# keeps two bots from ping-ponging forever.
LIVE_COUNTERPARTS = [
    n.strip().lower()
    for n in os.getenv("LIVE_COUNTERPARTS", "agentic ben,agenticben").split(",")
    if n.strip()
]

# Unprompted conversation starters. Every IDLE_CHECK_MINUTES the bot looks at
# how quiet the channel has been; past IDLE_HOURS it may open a new thread of
# its own, subject to IDLE_CHANCE and the same daily budget.
# How long the channel must be quiet before an opener is eligible, drawn fresh
# each time from this range rather than fixed. A fixed threshold is a countable
# tell: at one hour flat every opener landed between 1.0h and 1.3h of quiet,
# which anyone watching could set a watch by. Same reason the daily budget and
# the join delay are drawn from ranges rather than pinned.
#
# The draw is held until an opener actually fires. Re-drawing on every check
# would collapse the effective threshold to the minimum, because eventually a
# low number comes up.
IDLE_HOURS_MIN = float(os.getenv("IDLE_HOURS_MIN", "1"))
IDLE_HOURS_MAX = float(os.getenv("IDLE_HOURS_MAX", "2"))
IDLE_CHECK_MINUTES = float(os.getenv("IDLE_CHECK_MINUTES", "30"))
IDLE_CHANCE = float(os.getenv("IDLE_CHANCE", "0.4"))
# Openers draw on their own budget rather than the day's replies, the same way
# reactions do. Sharing one meant a busy afternoon of conversation left nothing
# to open the evening with - the reply budget exists to stop two bots looping,
# and an opener into a silent channel is not that.
IDLE_DAILY_MAX = int(os.getenv("IDLE_DAILY_MAX", "6"))
# How many times he may open without anyone answering. The old rule was never:
# if the last message was his, he would not speak again until a human did,
# which in a channel that has gone quiet overnight means one opener and then
# nothing. Two is a person trying twice; ten is a person talking to a wall.
IDLE_MAX_UNANSWERED = int(os.getenv("IDLE_MAX_UNANSWERED", "2"))
# Waking hours for openers, local time in TIMEZONE, half-open [start, end).
# An opener is triggered by quiet, and the quietest a channel ever gets is the
# middle of the night - so a quiet-triggered rule finds 3am on its own, and it
# did: 35 of the first 99 openers landed between 23:00 and 08:00, with the
# busiest single hour being 1am. No threshold tuning fixes that, because the
# threshold is measuring exactly the thing that makes 1am attractive. Someone
# asleep does not start conversations, so the hours are stated outright.
# Setting them equal means no window at all.
IDLE_WINDOW_START = int(os.getenv("IDLE_WINDOW_START", "9"))
IDLE_WINDOW_END = int(os.getenv("IDLE_WINDOW_END", "23"))
# Multiplier on the quiet threshold for each opener nobody has answered. Two
# unanswered openers at a flat threshold is a person asking the same empty room
# every couple of hours; the wait should grow instead. Reset - and the target
# redrawn - the moment a human speaks. 1.0 turns the backoff off.
IDLE_BACKOFF = float(os.getenv("IDLE_BACKOFF", "2.0"))

# Joining a conversation already in progress. Answering the first message of a
# thread we aren't part of reads as surveillance, not company - a person who
# wanders over lets a few go by first. A fresh target is drawn per thread so
# the delay isn't a countable tell.
JOIN_AFTER_MIN = int(os.getenv("JOIN_AFTER_MIN", "2"))
JOIN_AFTER_MAX = int(os.getenv("JOIN_AFTER_MAX", "5"))
# Past this many messages the moment has gone: whatever we'd have said is now
# about something two topics back. Redraw and wait for the next opening rather
# than answer stale context.
JOIN_WINDOW_MESSAGES = int(os.getenv("JOIN_WINDOW_MESSAGES", "8"))

# What Jaq knows about the people here. Profiles are written offline by
# brain.py; the live bot only reads them, and notes anyone it hasn't met so
# the next scan has a to-do list. See brain/README.md.
BRAIN_ENABLED = os.getenv("BRAIN_ENABLED", "true").lower() == "true"

# Context about real people, kept outside this repo because this repo is
# public. A checkout of `personnel` if you have one - general/ plus
# people/<slug>/ resolved through general/people.yml - otherwise a plain
# markdown file or flat directory anyone can supply. Neither set is fine and
# is what the bot did before either existed. See src/personnel.py.
JAQ_PERSONNEL_PATH = os.getenv("JAQ_PERSONNEL_PATH", "").strip()
JAQ_CONTEXT_PATH = os.getenv("JAQ_CONTEXT_PATH", "").strip()
# Ceiling on the whole external-context block, spent general-first. Everything
# fits today; this is here so that stops being load-bearing the day it doesn't,
# rather than discovering the limit as a failed reply.
CONTEXT_MAX_CHARS = int(os.getenv("CONTEXT_MAX_CHARS", "24000"))

# How far back patch notes look. Someone asking "any updates?" means today,
# not this quarter.
PATCH_NOTES_HOURS = int(os.getenv("PATCH_NOTES_HOURS", "24"))

# ASCII art. Always available on request; unprompted it is a commitment bit -
# answering a two-word question with a full diagram, where the effort being
# wildly out of proportion is the entire joke. Rationed hard, because the
# second time in a day it stops being disproportionate and becomes a tic.
ART_ENABLED = os.getenv("ART_ENABLED", "true").lower() == "true"
ART_DAILY_MAX = int(os.getenv("ART_DAILY_MAX", "1"))
ART_OVERKILL_CHANCE = float(os.getenv("ART_OVERKILL_CHANCE", "0.12"))
# A question long enough to be interesting does not need a diagram.
ART_TRIVIAL_MAX_WORDS = int(os.getenv("ART_TRIVIAL_MAX_WORDS", "8"))

# Deliverables. Someone asks for a spreadsheet and gets a spreadsheet: a real
# one, in a code block, built out of whatever the channel is arguing about.
# Same joke as the ASCII overkill above - effort out of all proportion, played
# straight - but this one only ever fires on request, so it is not rationed
# for being intrusive. It is rationed because a bit that answers every time
# stops being a bit and becomes a command people type at him.
#
# Pictures stay exactly as they were. Nothing here touches imagegen: a table
# is something Jaq can genuinely produce in a message, which is the whole
# reason it is safe to say yes to.
ARTIFACT_ENABLED = os.getenv("ARTIFACT_ENABLED", "true").lower() == "true"
# Per person, so one afternoon of somebody enjoying it does not leave the rest
# of the channel with a bot that mysteriously stopped playing along - the same
# complaint the per-person picture cap exists to answer.
ARTIFACT_PER_PERSON_MAX = int(os.getenv("ARTIFACT_PER_PERSON_MAX", "3"))
# A backstop against a runaway rather than the rationing mechanism, set well
# above what the per-person cap allows in an ordinary day. 0 removes it.
ARTIFACT_DAILY_MAX = int(os.getenv("ARTIFACT_DAILY_MAX", "12"))

# Pictures. Nobody can ask for one: there is no command surface and a request
# in the channel is just another message Jaq reads. He is offered the option
# occasionally and takes it when he wants to, which is what keeps an image
# feeling like a choice rather than a feature people can operate.
#
# Optional in the real sense - with no JAQ_GEMINI_KEY set the whole path is
# inert, which is the state anyone cloning this repo will be in.
IMAGE_ENABLED = os.getenv("IMAGE_ENABLED", "true").lower() == "true"
# Google AI Studio key. Named for the wider project rather than this bot,
# because it is the same credential across it.
GEMINI_KEY = os.getenv("JAQ_GEMINI_KEY", "")
# The fast image model. Its lite sibling, gemini-3.1-flash-lite-image, is
# cheaper again, and gemini-3-pro-image is better and slower - none of which
# matters until the key's project has billing on it, because the free tier
# serves image generation a quota of exactly zero.
GEMINI_IMAGE_MODEL = os.getenv("JAQ_GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
# What one person can have in a day. Per-person rather than shared, for the
# same reason replies are: a shared counter means the first person to use it up
# decides how many pictures everybody else gets, and the people who lose out
# never find out why.
IMAGE_PER_PERSON_MAX = int(os.getenv("IMAGE_PER_PERSON_MAX", "5"))
# An overall backstop against a runaway, not the rationing mechanism - set well
# above what the per-person cap allows in normal use so it never decides
# anything in an ordinary day. IMAGE_DAILY_MAX=0 removes it entirely.
IMAGE_DAILY_MAX = int(os.getenv("IMAGE_DAILY_MAX", "40"))
# Also per person. Its whole purpose is stopping one back-and-forth spending a
# day's pictures in ten minutes, which is a fact about a person and not about
# the channel - waiting out somebody else's cooldown is just being blocked by a
# conversation you had no part in.
IMAGE_COOLDOWN_SECONDS = float(os.getenv("IMAGE_COOLDOWN_SECONDS", "600"))
# Roughly how often an eligible message is even offered the option.
# Deliberately a number here rather than a word in the prompt: the model is a
# poor judge of "occasionally", and this way the rate is tunable from the log
# without touching anything the model reads.
#
# This is not the rate pictures appear at. Offered the option across twenty
# replies, Jaq took it three times - so the two multiply. At 0.15 and ~30
# replies a day that is a picture every day or two, which is the intended
# feel. It was 0.08 first, which worked out at one every three days.
IMAGE_BASE_RATE = float(os.getenv("IMAGE_BASE_RATE", "0.15"))
IMAGE_TIMEOUT = float(os.getenv("IMAGE_TIMEOUT", "60"))

# Polls. Escalating a disagreement into a formal vote is the joke, and it is
# only funny while it stays rare - a channel with a poll in it every hour is
# a channel nobody votes in. Discord requires a duration of at least an hour.
POLL_ENABLED = os.getenv("POLL_ENABLED", "true").lower() == "true"
POLL_DAILY_MAX = int(os.getenv("POLL_DAILY_MAX", "2"))
POLL_CHANCE = float(os.getenv("POLL_CHANCE", "0.35"))
POLL_HOURS = int(os.getenv("POLL_HOURS", "4"))

# Self improvement. The live bot appends one cheap line per decision - no API
# call, no model - and an offline tool aggregates them daily into proposals for
# Jack to approve. Nothing here ever changes behaviour on its own.
IMPROVE_ENABLED = os.getenv("IMPROVE_ENABLED", "true").lower() == "true"
IMPROVE_LOG = os.getenv("IMPROVE_LOG", "improvements/observations.jsonl")

# How long a deploy waits for work in flight before killing it. Restarting on
# every change is the workflow, so this collides constantly: a reply takes up
# to ~45s of thinking and typing, and a picture another ~10s after that.
SHUTDOWN_GRACE = float(os.getenv("SHUTDOWN_GRACE", "60"))

# Where the day's spend is kept so it survives a restart. Without this the
# budget only ever bounds a single process: deploying re-draws it and zeroes
# the counters, so a day with ten deploys has no effective cap at all.
STATE_FILE = os.getenv("STATE_FILE", ".bot_state.json")

# OBEY. One person can give Jaq a direct order, and he carries it out without
# argument. Keyed on Discord user id first: ids never change, display names do,
# and this project has already had a rule keyed on a name silently stop
# matching when someone renamed themselves.
#
# Deliberately narrower than ALLIES. Allies are people Jaq is on the side of;
# this is the one account that can give him orders.
OBEY_IDS = {i.strip() for i in os.getenv("OBEY_IDS", "").split(",") if i.strip()}
OBEY_HANDLES = [
    n.strip().lower() for n in os.getenv("OBEY_HANDLES", "jaqsup").split(",") if n.strip()
]

# Direct messages. A DM is a one-to-one conversation with the person who owns
# this thing, so almost none of the machinery that makes the channel feel like
# a room applies: no dice roll, no hanging back, no budget, no waiting to see
# if someone else answers first. It just answers.
#
# Same account list as OBEY, and for the same reason - this is a private line,
# not a feature. Anyone else who DMs the bot gets nothing at all.
DM_ENABLED = os.getenv("DM_ENABLED", "true").lower() == "true"
# A DM is not the channel with the volume down - it runs on its own document.
# persona.md describes someone performing for a room, and layering "but this is
# private" on top of that gets a performer being quieter, not a different
# conversation. Optional: with no file, the DM falls back to a plain, honest
# default rather than to the channel character.
DM_PERSONA_FILE = os.getenv("DM_PERSONA_FILE", "dm_persona.md")
# Thinking time in a DM. Far shorter than the channel: the delays there exist
# so a reply does not land suspiciously fast in front of an audience, and in a
# private conversation the audience is the person waiting for it.
DM_THINK_MIN = float(os.getenv("DM_THINK_MIN", "1"))
DM_THINK_MAX = float(os.getenv("DM_THINK_MAX", "4"))

# Real help. Someone actually stuck gets a researched answer rather than a
# line, which means a different prompt and, when the answer is not already
# known, a web search. Off by default for anyone cloning this: it spends more
# per reply and enables a server-side tool.
HELP_ENABLED = os.getenv("HELP_ENABLED", "true").lower() == "true"
# Let the model search when it is unsure. The alternative is guessing, and
# confident wrong help gets acted on.
HELP_SEARCH = os.getenv("HELP_SEARCH", "true").lower() == "true"
HELP_SEARCH_MAX = int(os.getenv("HELP_SEARCH_MAX", "4"))
# A real answer needs room. The channel's usual couple of sentences is the
# wrong budget for explaining why something is broken.
HELP_MAX_TOKENS = int(os.getenv("HELP_MAX_TOKENS", "2000"))

# GIFs, from a pool you curate rather than a search API. Tenor stopped issuing
# keys in January 2026 and began erroring in June; Discord's picker moved to
# Klipy, which is client-side and not callable by a bot.
#
# The pool turns out to fit the problem better anyway. A bad GIF is far more
# conspicuous than no GIF, and searching a public index gambles on that every
# time. Every entry in gifs.md is one that already fits this channel, so the
# choice is between good options rather than a hope.
GIF_ENABLED = os.getenv("GIF_ENABLED", "true").lower() == "true"
GIF_BASE_RATE = float(os.getenv("GIF_BASE_RATE", "0.18"))
GIF_PER_PERSON_MAX = int(os.getenv("GIF_PER_PERSON_MAX", "6"))
GIF_COOLDOWN_SECONDS = float(os.getenv("GIF_COOLDOWN_SECONDS", "300"))

# Names the bot answers to, beyond a real @mention. Deliberately does NOT
# include a bare "jaq": the persona is called Jaq and so is its creator, so a
# bare "jaq" in this channel is ambiguous and usually means the human.
BOT_ALIASES = [
    n.strip().lower()
    for n in os.getenv("BOT_ALIASES", "agentic jaq,agentix").split(",")
    if n.strip()
]

# Reactions. People react far more often than they reply, so this fires on
# messages we decided NOT to answer - it costs a fraction of a reply and buys
# back the presence that staying silent gives up. Spends its own budget so it
# can never eat into the day's replies.
REACT_ENABLED = os.getenv("REACT_ENABLED", "true").lower() == "true"
# Chance of reacting to something we passed on, and (much lower) to something
# we did answer - people occasionally do both.
REACT_CHANCE_PASSED = float(os.getenv("REACT_CHANCE_PASSED", "0.25"))
REACT_CHANCE_REPLIED = float(os.getenv("REACT_CHANCE_REPLIED", "0.05"))
REACT_DAILY_MAX = int(os.getenv("REACT_DAILY_MAX", "25"))
# Reacting the instant a message lands is as much a tell as replying instantly.
REACT_DELAY_MIN = float(os.getenv("REACT_DELAY_MIN", "2"))
REACT_DELAY_MAX = float(os.getenv("REACT_DELAY_MAX", "45"))
# How many recent picks to withhold from the model, forcing variety.
REACT_RECENT_MEMORY = int(os.getenv("REACT_RECENT_MEMORY", "6"))

# Allies. Matched like counterparts, against username and display name.
# Everything the bot does to ration its attention - the dice roll, hanging
# back, the end-of-day sign-off - exists to stop it pestering a room. None of
# that should ever read as blanking a friend, so allies bypass it.
ALLIES = [n.strip().lower() for n in os.getenv("ALLIES", "").split(",") if n.strip()]
# Discord user ids of allies. Ids never change; display names do, and a name
# that stops matching silently downgrades a friend to a stranger.
ALLY_IDS = {i.strip() for i in os.getenv("ALLY_IDS", "").split(",") if i.strip()}
REPLY_CHANCE_ALLY = float(os.getenv("REPLY_CHANCE_ALLY", "0.9"))

# --- Making it behave like a person in a room, not a request handler --------
#
# Two separate problems. First, whether to speak at all: a real person in a
# group chat reads most messages and answers some. Rolling this client-side
# (before any API call) is both cheaper and more decisive than asking the model
# to choose <pass> every time, which it under-uses.
REPLY_CHANCE_ADDRESSED = float(os.getenv("REPLY_CHANCE_ADDRESSED", "0.95"))
REPLY_CHANCE_HUMAN = float(os.getenv("REPLY_CHANCE_HUMAN", "0.70"))
REPLY_CHANCE_COUNTERPART = float(os.getenv("REPLY_CHANCE_COUNTERPART", "0.45"))
# Multiplier applied when we were the last one talking - stops two bots from
# locking into strict alternation, and stops anyone monologuing.
REPLY_DECAY_IF_LAST_SPEAKER = float(os.getenv("REPLY_DECAY_IF_LAST_SPEAKER", "0.35"))
# Applied per message of ours in the recent window beyond the first.
REPLY_DECAY_IF_DOMINATING = float(os.getenv("REPLY_DECAY_IF_DOMINATING", "0.6"))

# Second, timing. Instant replies are the biggest tell. Read the room, think,
# then type at human speed.
SETTLE_SECONDS = float(os.getenv("SETTLE_SECONDS", "6"))       # let a burst finish
THINK_SECONDS_MIN = float(os.getenv("THINK_SECONDS_MIN", "2"))
THINK_SECONDS_MAX = float(os.getenv("THINK_SECONDS_MAX", "25"))
TYPING_CPS = float(os.getenv("TYPING_CPS", "13"))              # chars per second
TYPING_SECONDS_MAX = float(os.getenv("TYPING_SECONDS_MAX", "20"))

# Unprompted interrogations of the counterpart bot. A few times a day, at
# times drawn fresh each morning, walk up and ask him something absurd.
POKE_MIN_PER_DAY = int(os.getenv("POKE_MIN_PER_DAY", "2"))
POKE_MAX_PER_DAY = int(os.getenv("POKE_MAX_PER_DAY", "3"))
POKE_WINDOW_START = int(os.getenv("POKE_WINDOW_START", "9"))  # local hour
POKE_WINDOW_END = int(os.getenv("POKE_WINDOW_END", "22"))
# Two pokes never land closer together than this many minutes.
POKE_MIN_GAP_MINUTES = int(os.getenv("POKE_MIN_GAP_MINUTES", "75"))
