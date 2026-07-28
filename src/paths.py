"""Where things live, defined once.

Every module used to work out the repo root from its own __file__, which meant
six copies of the same assumption and six things to fix the moment any file
moved. Code lives in src/, content and configuration live at the root beside
it, and this is the only place that relationship is written down.
"""

from __future__ import annotations

import os

# src/paths.py -> src/ -> repo root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def at_root(*parts: str) -> str:
    """Absolute path to something beside the repo root."""
    return os.path.join(ROOT, *parts)
