"""Shared fixtures.

bot.py reads its whole configuration at import time, and two of those reads are
`os.environ[...]` rather than `.getenv` — so importing it without a token or
channel raises. Everything here therefore sets a fake environment *before* the
import, and the real .env is deliberately not loaded: tests assert against the
documented defaults, not against whatever this machine happens to be running.
"""

from __future__ import annotations

import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# Must precede `import bot`. dotenv's load_dotenv() will not overwrite a
# variable that is already set, so these also shield the suite from the real
# .env sitting next to it.
os.environ.update(
    {
        "DISCORD_TOKEN": "test-token",
        "CHANNEL_ID": "1",
        "ALLIES": "real jaq,jaqsup",
        "LIVE_COUNTERPARTS": "agentic ben,agenticben",
        "BRAIN_ENABLED": "false",
    }
)


# --- fake Discord objects ---------------------------------------------------
#
# The reply logic only ever reads a handful of attributes off a message. Faking
# those is far cheaper than a real gateway connection — and the fact that this
# file has to exist at all is the argument for pulling the decision logic out
# into something that takes plain values.


class FakeAuthor:
    def __init__(self, display: str, name: str = "", is_bot: bool = False):
        self.display_name = display
        self.name = name or display.lower().replace(" ", "")
        self.bot = is_bot
        self.id = abs(hash(display)) % 10**9


class FakeMessage:
    def __init__(self, author: FakeAuthor, content: str = "hello", mentions=None):
        self.author = author
        self.clean_content = content
        self.mentions = mentions or []
        self.id = abs(hash(content)) % 10**9
        self.channel = None


@pytest.fixture(scope="session")
def bot_module():
    import bot

    return bot


@pytest.fixture
def persona_bot(bot_module):
    """A PersonaBot with no Discord connection behind it.

    discord.Client.user is a read-only property, so it has to be shadowed on a
    subclass rather than assigned on the instance.
    """
    me = types.SimpleNamespace(id=999, display_name="agentix", name="agentix")

    class Testable(bot_module.PersonaBot):
        user = me

    b = Testable.__new__(Testable)
    b._reply_day = __import__('datetime').date(2026, 7, 28)
    b._reactions_today = 0
    b._replies_today = 0
    b._daily_budget = 100
    b._brushed_off_today = False
    b._messages_waited = 0
    b._hang_back_target = 3
    b._recent_reactions = __import__("collections").deque(maxlen=6)
    b._pending = set()
    b._save_day = lambda: None  # persistence covered in test_daily_state
    return b


@pytest.fixture
def jack():
    return FakeAuthor("Real Jaq", "jaqsup")


@pytest.fixture
def zack():
    return FakeAuthor("Zack Kross", "slaymakerlol")


@pytest.fixture
def ben_bot():
    return FakeAuthor("Agentic Ben", "agenticben", is_bot=True)


@pytest.fixture
def stranger():
    return FakeAuthor("wishxd", "giftxd")
