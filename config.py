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

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
PERSONA_FILE = os.getenv("PERSONA_FILE", "persona.md")
# How conversation works, kept apart from who Jaq is so the two can be
# edited independently. Optional - absent file just means no block.
PSYCHOLOGY_FILE = os.getenv("PSYCHOLOGY_FILE", "psychology.md")
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
IDLE_HOURS = float(os.getenv("IDLE_HOURS", "5"))
IDLE_CHECK_MINUTES = float(os.getenv("IDLE_CHECK_MINUTES", "30"))
IDLE_CHANCE = float(os.getenv("IDLE_CHANCE", "0.4"))

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

# How far back patch notes look. Someone asking "any updates?" means today,
# not this quarter.
PATCH_NOTES_HOURS = int(os.getenv("PATCH_NOTES_HOURS", "24"))

# Where the day's spend is kept so it survives a restart. Without this the
# budget only ever bounds a single process: deploying re-draws it and zeroes
# the counters, so a day with ten deploys has no effective cap at all.
STATE_FILE = os.getenv("STATE_FILE", ".bot_state.json")

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
