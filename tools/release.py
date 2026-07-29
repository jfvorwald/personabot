"""Cut a version tag at a pivot point.

    .venv/bin/python tools/release.py              what would be tagged, no tag
    .venv/bin/python tools/release.py --tag        create it
    .venv/bin/python tools/release.py --tag --major

A version here is not a schedule and not a number of commits. It is **one
major feature landing**, and the tag is what bounds the commits that delivered
it. Tonight's picture work was ten commits and one version; a good day of small
fixes is none.

The scheme is `v0.MINOR.PATCH` while this is pre-1.0:

    --minor   (default)  a feature landed. Pictures, polls, the brain.
    --patch              a span of fixes with no new capability.
    --major              reserved for 1.0, when the persona stops changing
                         shape every evening.

Tags are annotated and carry the commit subjects in the span, so `git show
v0.6.0` explains what that version was without anyone maintaining a changelog.
The subjects are already written to be read out loud - see CLAUDE.md - which
makes them serviceable release notes for free.

Nothing here pushes. A tag is local until you say otherwise.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

TAG_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def latest_tag() -> str | None:
    """The highest version tag, or None on a repo that has never been tagged."""
    tags = [t for t in git("tag", "-l").splitlines() if TAG_PATTERN.match(t)]
    if not tags:
        return None
    return max(tags, key=lambda t: tuple(int(n) for n in TAG_PATTERN.match(t).groups()))


def next_version(current: str | None, bump: str) -> str:
    if current is None:
        return "v0.1.0"
    major, minor, patch = (int(n) for n in TAG_PATTERN.match(current).groups())
    if bump == "major":
        return f"v{major + 1}.0.0"
    if bump == "patch":
        return f"v{major}.{minor}.{patch + 1}"
    return f"v{major}.{minor + 1}.0"


def commits_since(tag: str | None) -> list[str]:
    span = f"{tag}..HEAD" if tag else "HEAD"
    out = git("log", "--format=%s", span)
    return [line for line in out.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", action="store_true", help="actually create it")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--major", action="store_true")
    group.add_argument("--patch", action="store_true")
    parser.add_argument("--name", help="a short name for what this version is")
    args = parser.parse_args()

    if git("status", "--porcelain"):
        print("Working tree is dirty. Commit first - a tag should point at a")
        print("state you can actually return to.")
        return 1

    current = latest_tag()
    bump = "major" if args.major else "patch" if args.patch else "minor"
    version = next_version(current, bump)
    subjects = commits_since(current)

    if not subjects:
        print(f"Nothing since {current}. A tag on the same commit says nothing.")
        return 1

    print(f"{current or '(no tags yet)'} -> {version}")
    print(f"{len(subjects)} commit{'s' if len(subjects) != 1 else ''} in this span:\n")
    for subject in subjects:
        print(f"  {subject}")

    headline = args.name or subjects[0]
    body = "\n".join(f"- {s}" for s in subjects)
    message = f"{version} - {headline}\n\n{body}\n"

    if not args.tag:
        print("\n--- tag message that would be written ---")
        print(message)
        print("Re-run with --tag to create it. Nothing has been changed.")
        return 0

    git("tag", "-a", version, "-m", message)
    print(f"\nCreated {version}. It is local - push with:")
    print(f"  git push origin {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
