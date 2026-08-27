"""Straightening a table the model drew.

Asking for aligned columns in the prompt does not work, because a model cannot
count characters - it drifts a cell by one or two and the grid shears. In a
spreadsheet the alignment is the whole joke, so this is the same bargain the
rest of guard.py makes: the prompt asks, and this makes it true on the way out.

The danger is the opposite mistake. ASCII art draws with pipes, and a drawing
put through a table formatter is destroyed. Every test about leaving things
alone is guarding that.
"""

from __future__ import annotations

import guard


CROOKED = """```
+------+-------+
| NAME | ROLE |
+------+-------+
| zack | tank    |
| ben   | dps |
+------+-------+
```"""


def test_a_crooked_table_comes_out_square():
    out = guard.align_tables(CROOKED)
    rows = [ln for ln in out.split("\n") if ln.startswith("|") or ln.startswith("+")]
    assert len({len(r) for r in rows}) == 1, "rows are still different widths"


def test_the_content_survives_alignment():
    out = guard.align_tables(CROOKED)
    for word in ("NAME", "ROLE", "zack", "tank", "ben", "dps"):
        assert word in out


def test_alignment_is_idempotent():
    once = guard.align_tables(CROOKED)
    assert guard.align_tables(once) == once


def test_ascii_art_is_left_alone():
    """Pipes as drawing strokes, not cell borders. This is the one that
    matters: a drawing reflowed into a grid is ruined."""
    art = """```
   .---.
  | o o |
  |  ^  |
  | \\_/ |
   '---'
```"""
    assert guard.align_tables(art) == art


def test_a_pipe_in_ordinary_speech_is_punctuation():
    text = "pipe it | through grep | like that"
    assert guard.align_tables(text) == text


def test_a_table_outside_a_fence_is_left_alone():
    """Discord renders it proportionally anyway, so squaring it is pointless
    and would mean reflowing text nobody asked us to touch."""
    text = "| a | b |\n| c | d |\nplain text"
    assert guard.align_tables(text) == text


def test_an_unclosed_fence_is_left_alone():
    assert guard.align_tables("```\n| a | b |\n| c | d |") == "```\n| a | b |\n| c | d |"


def test_titles_and_footnotes_inside_the_block_survive():
    text = """```
ATTENDANCE LEDGER v4.2 FINAL FINAL
+------+-------+
| NAME | SHOWS |
+------+-------+
| zack | 40%     |
+------+-------+
footnote 1: do not audit row 5
```"""
    out = guard.align_tables(text)
    assert "ATTENDANCE LEDGER v4.2 FINAL FINAL" in out
    assert "footnote 1: do not audit row 5" in out


def test_a_row_with_the_wrong_cell_count_is_left_as_written():
    """Guessing which cell was meant to be merged is worse than leaving it."""
    text = """```
+------+-------+
| NAME | ROLE |
+------+-------+
| zack | tank |
| this row is one long cell |
+------+-------+
```"""
    out = guard.align_tables(text)
    assert "| this row is one long cell |" in out


def test_a_markdown_rule_keeps_its_own_characters():
    """A |---| separator must not come back as +---+."""
    text = "```\n| name | role |\n|---|---|\n| zack | tank |\n```"
    out = guard.align_tables(text)
    assert "+" not in out
    assert "|------|------|" in out


def test_a_double_rule_keeps_its_equals_signs():
    text = "```\n+===+===+\n| ab | c |\n| d | ef |\n+===+===+\n```"
    out = guard.align_tables(text)
    assert "=" in out and "-" not in out


def test_text_with_no_fence_is_returned_untouched():
    assert guard.align_tables("just a line") == "just a line"


def test_an_indented_block_keeps_its_indentation():
    text = "```\n  | a | b |\n  | ccc | d |\n  | e | f |\n```"
    out = guard.align_tables(text)
    assert all(
        ln.startswith("  |") for ln in out.split("\n") if ln.strip().startswith("|")
    )


def test_only_the_fenced_part_is_touched():
    text = "before | not | a table\n```\n| a | b |\n| ccc | d |\n| e | f |\n```\nafter | also | not"
    out = guard.align_tables(text)
    assert out.startswith("before | not | a table")
    assert out.endswith("after | also | not")


# --- width, which is the other half of "it has to read on a phone" ----------


def test_a_wide_table_is_brought_inside_the_cap():
    """The model ignores a width instruction because staying inside one means
    counting characters. Counted here instead."""
    wide = (
        "```\n"
        "| MEMBER        | WED 7PM SHOWS | FLASK BROUGHT | EXCUSE ON FILE           |\n"
        "| slaymakerlol  | 12/12         | Y             | n/a                      |\n"
        "| mudbucket1337 | 3/12          | N             | last week was different  |\n"
        "```"
    )
    out = guard.align_tables(wide)
    widest = max(len(ln) for ln in out.split("\n") if ln.startswith("|"))
    assert widest <= guard.MAX_TABLE_WIDTH, widest


def test_a_narrow_table_is_not_squeezed():
    """The cap is a backstop, not a target - it must not touch what fits."""
    text = "```\n| a | b |\n| ccc | d |\n| e | f |\n```"
    out = guard.align_tables(text)
    assert "| ccc | d |" in out


def test_columns_are_never_shaved_to_nothing():
    """Past a point a squeezed table is no more readable than a wrapped one,
    so being too wide becomes the better failure."""
    text = "```\n" + "\n".join(
        "| " + " | ".join("x" * 20 for _ in range(8)) + " |" for _ in range(3)
    ) + "\n```"
    out = guard.align_tables(text)
    for line in out.split("\n"):
        if line.startswith("|"):
            for cell in line[1:-1].split("|"):
                assert len(cell.strip()) >= guard.MIN_COLUMN_WIDTH


def test_the_widest_column_gives_up_the_space():
    """Shaving the last column every time would gut whichever field happened
    to be on the right."""
    text = (
        "```\n"
        "| ab | " + "z" * 40 + " |\n"
        "| cd | " + "y" * 40 + " |\n"
        "```"
    )
    out = guard.align_tables(text)
    first = [ln[1:-1].split("|")[0].strip() for ln in out.split("\n") if ln.startswith("|")]
    assert "ab" in first and "cd" in first, "the narrow column was shaved instead"


def test_a_capped_table_is_still_square():
    wide = (
        "```\n"
        "| MEMBER        | SHOWS UP EVERY WEEK | EXCUSE ON FILE HERE |\n"
        "| zack          | yes                 | none at all         |\n"
        "| mudbucket1337 | no                  | last week different |\n"
        "```"
    )
    out = guard.align_tables(wide)
    rows = [ln for ln in out.split("\n") if ln.startswith("|")]
    assert len({len(r) for r in rows}) == 1
