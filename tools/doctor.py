"""Check each layer of the setup independently, in order.

    .venv/bin/python doctor.py           # checks 1-4, sends nothing
    .venv/bin/python doctor.py --send    # also posts a throwaway test message

Values come from .env, or from inline environment variables:

    DISCORD_TOKEN='...' ANTHROPIC_API_KEY='...' CHANNEL_ID='...' \\
        .venv/bin/python doctor.py

Each check prints PASS or FAIL with the specific fix. Stops at the first
failure, since later checks depend on earlier ones.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

load_dotenv(os.path.join(ROOT, ".env"))

SEND = "--send" in sys.argv


def ok(step: str, detail: str = "") -> bool:
    print(f"  PASS  {step}" + (f" - {detail}" if detail else ""))
    return True


def fail(step: str, why: str, fix: str) -> bool:
    print(f"  FAIL  {step}\n        {why}\n        FIX: {fix}")
    return False


def check_1_config() -> bool:
    print("\n[1/4] Configuration")
    token = (os.getenv("DISCORD_TOKEN") or "").strip()
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    channel = (os.getenv("CHANNEL_ID") or "").strip()

    if not token:
        return fail("DISCORD_TOKEN", "not set", "fill .env, or pass it inline")
    if token.count(".") != 2:
        return fail(
            "DISCORD_TOKEN",
            f"expected 3 dot-separated parts, got {token.count('.') + 1}",
            "copy the Bot-tab token, not the Client Secret or Application ID",
        )
    ok("DISCORD_TOKEN", f"{len(token)} chars")

    if not key:
        return fail("ANTHROPIC_API_KEY", "not set", "fill .env, or pass it inline")
    if not key.startswith("sk-ant-"):
        return fail(
            "ANTHROPIC_API_KEY",
            f"starts with {key[:8]!r}, expected 'sk-ant-'",
            "grab the key from console.anthropic.com -> API Keys",
        )
    ok("ANTHROPIC_API_KEY", f"{len(key)} chars")

    if not re.fullmatch(r"\d{17,20}", channel):
        return fail(
            "CHANNEL_ID",
            f"{channel!r} is not 17-20 digits",
            "right-click the channel -> Copy Channel ID (Developer Mode on)",
        )
    ok("CHANNEL_ID", channel)

    persona = os.getenv("PERSONA_FILE", "persona.md")
    if not os.path.exists(persona):
        return fail(persona, "file not found", "cp persona.example.md persona.md")
    return ok(persona, f"{os.path.getsize(persona)} bytes")


async def check_2_anthropic() -> bool:
    print("\n[2/4] Anthropic API")
    import anthropic

    client = anthropic.AsyncAnthropic()
    try:
        r = await client.messages.create(
            model=os.getenv("MODEL", "claude-opus-5"),
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        )
    except anthropic.AuthenticationError:
        return fail("auth", "key rejected", "check ANTHROPIC_API_KEY is current")
    except anthropic.PermissionDeniedError as e:
        return fail("permission", str(e), "key may lack access to this model")
    except anthropic.BadRequestError as e:
        msg = str(e)
        if "credit" in msg.lower() or "billing" in msg.lower():
            return fail("billing", msg, "add credits at console.anthropic.com -> Billing")
        return fail("request", msg, "unexpected - paste this output")
    except Exception as e:
        return fail(type(e).__name__, str(e), "network or API problem")
    return ok("round trip", f"{r.usage.input_tokens} in / {r.usage.output_tokens} out")


async def check_3_and_4_discord() -> bool:
    print("\n[3/4] Discord login")
    import discord

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    result = {"ok": False}

    @client.event
    async def on_ready():
        try:
            ok("logged in", f"{client.user} (id={client.user.id})")

            print("\n[4/4] Channel access")
            cid = int(os.environ["CHANNEL_ID"])
            try:
                channel = client.get_channel(cid) or await client.fetch_channel(cid)
            except discord.NotFound:
                fail("fetch channel", "no such channel", "wrong CHANNEL_ID")
                return
            except discord.Forbidden:
                fail(
                    "fetch channel",
                    "bot cannot see it",
                    "invite the bot to that server and grant View Channel",
                )
                return
            ok("channel", f"#{channel.name} in {channel.guild.name}")

            perms = channel.permissions_for(channel.guild.me)
            for name in ("view_channel", "send_messages", "read_message_history"):
                if not getattr(perms, name):
                    fail(name, "not granted", "re-invite with this permission checked")
                    return
                ok(name)

            count, blank = 0, 0
            async for m in channel.history(limit=10):
                count += 1
                if not m.clean_content.strip():
                    blank += 1
            if count and blank == count:
                fail(
                    "read history",
                    f"all {count} messages came back empty",
                    "enable MESSAGE CONTENT INTENT in the Developer Portal",
                )
                return
            ok("read history", f"{count} messages, {count - blank} with readable text")

            if SEND:
                sent = await channel.send("personabot doctor: test message, ignore.")
                ok("send", f"posted message id {sent.id}")
            else:
                print("  SKIP  send - re-run with --send to test posting")

            result["ok"] = True
        finally:
            await client.close()

    try:
        await client.start(os.environ["DISCORD_TOKEN"])
    except discord.LoginFailure:
        return fail("login", "token rejected", "Reset Token in the Developer Portal")
    except discord.PrivilegedIntentsRequired:
        return fail(
            "intents",
            "MESSAGE CONTENT INTENT is off",
            "Developer Portal -> Bot -> Privileged Gateway Intents -> enable, Save",
        )
    return result["ok"]


async def check_5_images() -> bool:
    """Optional, and skipped entirely when no key is configured.

    Worth its own check because the failure it catches is invisible in normal
    use: a wrong model name or a key without image access produces no picture,
    and the bot is built to say nothing when that happens.
    """
    print("\n[5] Image generation (optional)")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "src"))
    import imagegen

    key = os.getenv("JAQ_GEMINI_KEY", "")
    if not imagegen.available(key):
        print("  SKIP  no JAQ_GEMINI_KEY set - pictures are off, which is fine")
        return True

    model = os.getenv("JAQ_GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    data = await imagegen.generate(
        "a plain grey circle on a white background", key=key, model=model
    )
    if not data:
        return fail(
            "render",
            f"no image came back from {model}",
            "check the key at aistudio.google.com/apikey, and that "
            "JAQ_GEMINI_IMAGE_MODEL names a current image model",
        )
    return ok("render", f"{model}, {len(data) // 1024} KB")


async def main() -> int:
    print("personabot doctor")
    if not check_1_config():
        return 1
    if not await check_2_anthropic():
        return 1
    if not await check_3_and_4_discord():
        return 1
    if not await check_5_images():
        return 1
    print("\nAll checks passed. Run:  .venv/bin/python src/bot.py --now")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
