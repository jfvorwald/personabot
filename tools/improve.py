"""The daily self-improvement pass. Run by a human or a timer, never by the bot.

    .venv/bin/python tools/improve.py            look at the last 24 hours
    .venv/bin/python tools/improve.py --hours 72
    .venv/bin/python tools/improve.py --dry-run  measurements only, no model

Reads what the bot actually posted, measures it, and asks for proposals. It
writes two things and changes nothing:

    improvements/log/YYYY-MM-DD.md   the day's findings, kept
    improvements/PROPOSALS.md        the open list, rewritten each run

Nothing here takes effect. Jack reads the proposals and decides, the same
contract brain.py has, and for the same reason: generated content about a
private channel gets reviewed before it goes anywhere near the bot.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import anthropic
import discord

import improve
from config import (
    CHANNEL_ID,
    DISCORD_TOKEN,
    EFFORT,
    IMPROVE_LOG,
    LIVE_COUNTERPARTS,
    MODEL,
    TIMEZONE,
)
from paths import at_root
from prompts import IMPROVE_PROMPT

OUT_DIR = "improvements"


async def pull(hours: int) -> tuple[list, int]:
    """Everything said in the channel in the window, oldest first."""
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    got: dict = {"messages": [], "me": 0}

    @client.event
    async def on_ready():
        try:
            channel = client.get_channel(CHANNEL_ID) or await client.fetch_channel(
                CHANNEL_ID
            )
            cutoff = discord.utils.utcnow() - datetime.timedelta(hours=hours)
            msgs = [m async for m in channel.history(limit=1000, after=cutoff)]
            got["messages"] = msgs
            got["me"] = client.user.id
        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)
    return got["messages"], got["me"]


def measure(messages: list, me: int, records: list[dict]) -> str:
    """Everything the model should not have to count for itself."""
    mine = [m.clean_content for m in messages if m.author.id == me and m.clean_content.strip()]
    counterpart = [
        m for m in messages
        if any(n in m.author.display_name.lower() for n in LIVE_COUNTERPARTS)
    ]
    humans = [m for m in messages if not m.author.bot]

    # How often did anyone pick up what he said?
    answered = 0
    for i, m in enumerate(messages[:-1]):
        if m.author.id == me and messages[i + 1].author.id != me:
            answered += 1
    mine_count = sum(1 for m in messages if m.author.id == me)

    reactions = sum(
        len(m.reactions) for m in messages if m.author.id == me and m.reactions
    )

    lines = [
        f"Window: {len(messages)} messages in the channel.",
        f"  his messages: {mine_count}",
        f"  counterpart bot: {len(counterpart)}",
        f"  humans: {len(humans)}",
        "",
        f"Someone said something after {answered} of his {mine_count} messages.",
        f"Reactions received: {reactions}.",
        "",
    ]

    profile = improve.length_profile(mine)
    lines += [
        f"Length: median {profile['median']} chars, longest {profile['longest']}, "
        f"{profile['over_300']} over 300.",
        "",
    ]

    tics = improve.overused(mine)
    if tics:
        lines.append("Words appearing in a large share of his messages:")
        lines += [f"  {w}: {share:.0%}" for w, share in tics[:10]]
        lines.append("")

    openers = improve.opening_habits(mine)
    if openers:
        lines.append("How his messages start:")
        lines += [f"  '{w}...': {share:.0%}" for w, share in openers[:6]]
        lines.append("")

    phrases = improve.repeated_phrases(mine)
    if phrases:
        lines.append("Phrases he used more than twice:")
        lines += [f"  '{p}' x{n}" for p, n in phrases[:10]]
        lines.append("")

    if records:
        stats = improve.engagement(records)
        lines += [
            f"From his own log: {stats['replied']} replies, {stats['passed']} "
            f"deliberate silences.",
            f"  paths taken: {stats['paths']}",
            "",
        ]
    return "\n".join(lines)


async def propose(measurements: str, transcript: str) -> str:
    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=IMPROVE_PROMPT,
        output_config={"effort": EFFORT},
        messages=[
            {
                "role": "user",
                "content": (
                    f"MEASUREMENTS\n\n{measurements}\n\n"
                    f"TRANSCRIPT\n\n{transcript[-12000:]}"
                ),
            }
        ],
    )
    if response.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in response.content if b.type == "text").strip()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the measurements and stop, no model call",
    )
    args = parser.parse_args()

    messages, me = await pull(args.hours)
    if not messages:
        print("Nothing said in the window; nothing to learn from.")
        return 0

    records = improve.read_records(
        at_root(IMPROVE_LOG),
        since=(
            datetime.datetime.now(TIMEZONE) - datetime.timedelta(hours=args.hours)
        ).isoformat(timespec="seconds"),
    )
    measurements = measure(messages, me, records)
    print(measurements)
    if args.dry_run:
        return 0

    transcript = "\n".join(
        f"{m.author.display_name}: {m.clean_content}"
        for m in messages
        if m.clean_content.strip()
    )
    proposals = await propose(measurements, transcript)
    if not proposals:
        print("No proposals came back.")
        return 1

    today = datetime.datetime.now(TIMEZONE).date().isoformat()
    os.makedirs(at_root(f"{OUT_DIR}/log"), exist_ok=True)
    entry = f"# {today}\n\n## Measured\n\n```\n{measurements}```\n\n## Proposed\n\n{proposals}\n"
    with open(at_root(f"{OUT_DIR}/log/{today}.md"), "w", encoding="utf-8") as f:
        f.write(entry)
    with open(at_root(f"{OUT_DIR}/PROPOSALS.md"), "w", encoding="utf-8") as f:
        f.write(
            f"# Open proposals\n\nFrom the last {args.hours}h, generated {today}.\n"
            f"Nothing here has been applied.\n\n{proposals}\n"
        )

    print("\n" + "=" * 70)
    print(proposals)
    print("=" * 70)
    print(f"\nWritten to {OUT_DIR}/PROPOSALS.md and {OUT_DIR}/log/{today}.md")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
