"""What was done to Jaq recently.

The repo is the source of truth: commits are real, dated, and already written,
so nothing here has to be maintained by hand. Reading them is the only part of
patch notes that code has to do - turning them into something worth reading is
the model's job.

Deliberately read-only and failure-tolerant. If git is missing, the working
directory is not a repo, or the command hangs, this returns nothing and the
caller falls back to the no-news path. Patch notes are a joke, not a feature
worth crashing a live bot over.
"""

from __future__ import annotations

import subprocess

# Subjects matching these are housekeeping - real commits, but nothing anyone
# in a group chat would want read out.
BORING = (
    "merge branch",
    "merge pull request",
    "bump version",
    "typo",
    "whitespace",
)


def recent_commits(hours: int = 24, cwd: str | None = None, limit: int = 25) -> list[str]:
    """Commit subjects from the last `hours`, newest first.

    Returns an empty list on any failure, which the caller treats the same as
    "nothing happened" - a bot that crashes because git moved is worse than a
    bot with no news.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"--since={hours} hours ago",
                "--no-merges",
                "--pretty=format:%s",
            ],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []

    subjects = []
    for line in result.stdout.splitlines():
        subject = line.strip()
        if not subject:
            continue
        if any(b in subject.lower() for b in BORING):
            continue
        subjects.append(subject)
    return subjects[:limit]


def summarise(subjects: list[str]) -> str:
    """Render the commit list for the prompt. Empty string if there is nothing."""
    if not subjects:
        return ""
    return "\n".join(f"- {s}" for s in subjects)
