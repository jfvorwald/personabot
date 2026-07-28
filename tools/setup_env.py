"""Interactive one-shot writer for .env - avoids editor/path confusion.

Run it from your own terminal:  .venv/bin/python setup_env.py

Secrets are read with hidden input, so they land in .env and nowhere else:
not your shell history, not your scrollback.
"""

from __future__ import annotations

import os
import re
import sys
from getpass import getpass

ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
)

FIELDS = [
    ("DISCORD_TOKEN", "Discord bot token (Bot tab -> Reset Token)", True),
    ("ANTHROPIC_API_KEY", "Anthropic API key (starts sk-ant-)", True),
    ("CHANNEL_ID", "Discord channel ID (18-19 digits)", False),
]


def validate(key: str, value: str) -> str | None:
    """Return an error string, or None if the value looks usable."""
    if key == "CHANNEL_ID" and not re.fullmatch(r"\d{17,20}", value):
        return "expected 17-20 digits - that looks like the wrong value"
    if key == "ANTHROPIC_API_KEY" and not value.startswith("sk-ant-"):
        return "Anthropic keys start with 'sk-ant-'"
    if key == "DISCORD_TOKEN":
        if value.startswith("sk-ant-"):
            return "that's the Anthropic key, not the Discord token"
        if value.count(".") != 2:
            return "expected three dot-separated parts - check you copied the bot token"
    return None


def prompt(key: str, label: str, secret: bool) -> str:
    while True:
        raw = getpass(f"{label}: ") if secret else input(f"{label}: ")
        # Strip quotes and stray whitespace from a sloppy paste.
        value = raw.strip().strip('"').strip("'").replace("\n", "").replace("\r", "")
        if not value:
            print("  -> empty, try again")
            continue
        err = validate(key, value)
        if err:
            print(f"  -> {err}")
            if input("  keep it anyway? [y/N] ").strip().lower() != "y":
                continue
        return value


def main() -> int:
    if not os.path.exists(ENV_PATH):
        print(f"No .env at {ENV_PATH} - copy .env.example first.", file=sys.stderr)
        return 1

    with open(ENV_PATH, encoding="utf-8") as f:
        lines = f.read().splitlines()

    print(f"Writing to {ENV_PATH}\nInput is hidden for the two secrets.\n")
    values = {key: prompt(key, label, secret) for key, label, secret in FIELDS}

    seen = set()
    for i, line in enumerate(lines):
        for key, value in values.items():
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                seen.add(key)
    # Append anything the template didn't already have a line for.
    for key, value in values.items():
        if key not in seen:
            lines.append(f"{key}={value}")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(ENV_PATH, 0o600)

    print("\nSaved. Verify with:  .venv/bin/python setup_env.py --check")
    return 0


def check() -> int:
    from dotenv import dotenv_values

    config = dotenv_values(ENV_PATH)
    ok = True
    for key, _, secret in FIELDS:
        value = (config.get(key) or "").strip()
        if not value:
            print(f"{key:20} MISSING")
            ok = False
        elif secret:
            print(f"{key:20} set ({len(value)} chars, starts {value[:8]}...)")
        else:
            print(f"{key:20} {value}")
    print("READY" if ok else "NOT READY")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else main())
