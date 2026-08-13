"""External context: which source wins, what it reads, and what it refuses.

The three things worth pinning here are the resolution order, the fact that
nothing in this path can raise into a reply, and that a slug never becomes a
path outside the checkout. The last one is the reason the manifest is validated
at all: it maps ids to directory names, and it is hand-edited.
"""

from __future__ import annotations

import os

import pytest

import personnel
from personnel import MarkdownProvider, NullProvider, PersonnelProvider


BIG = 10**9  # No budget pressure unless a test is about budget pressure.


def build(tmp_path, manifest="", general=None, people=None):
    """A personnel checkout on disk. Returns its root."""
    root = tmp_path / "personnel"
    (root / "general").mkdir(parents=True)
    (root / "general" / "people.yml").write_text(manifest, encoding="utf-8")
    for name, text in (general or {}).items():
        target = root / "general" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for slug, files in (people or {}).items():
        for name, text in files.items():
            target = root / "people" / slug / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    return str(root)


# --- resolution order ------------------------------------------------------


@pytest.fixture
def unresolved(monkeypatch):
    """Force the provider to be worked out again, and put it back after."""
    monkeypatch.setattr(personnel, "_provider", None)
    yield
    personnel._provider = None


def configure(monkeypatch, personnel_path="", context_path=""):
    import config

    monkeypatch.setattr(config, "JAQ_PERSONNEL_PATH", personnel_path)
    monkeypatch.setattr(config, "JAQ_CONTEXT_PATH", context_path)


def test_personnel_path_wins(tmp_path, monkeypatch, unresolved):
    root = build(tmp_path)
    other = tmp_path / "plain.md"
    other.write_text("plain", encoding="utf-8")
    configure(monkeypatch, root, str(other))
    assert isinstance(personnel.provider(), PersonnelProvider)


def test_markdown_used_when_no_personnel(tmp_path, monkeypatch, unresolved):
    other = tmp_path / "plain.md"
    other.write_text("plain", encoding="utf-8")
    configure(monkeypatch, "", str(other))
    assert isinstance(personnel.provider(), MarkdownProvider)


def test_nothing_configured_is_not_an_error(monkeypatch, unresolved):
    configure(monkeypatch)
    assert isinstance(personnel.provider(), NullProvider)
    assert personnel.provider().load_context("general", BIG) is None
    assert personnel.load_for({1, 2, 3}) == ""


def test_bad_personnel_path_falls_through_rather_than_raising(
    tmp_path, monkeypatch, unresolved
):
    """A moved checkout costs the context, never the bot."""
    other = tmp_path / "plain.md"
    other.write_text("plain", encoding="utf-8")
    configure(monkeypatch, str(tmp_path / "gone"), str(other))
    assert isinstance(personnel.provider(), MarkdownProvider)


def test_both_paths_bad_lands_on_null(tmp_path, monkeypatch, unresolved):
    configure(monkeypatch, str(tmp_path / "gone"), str(tmp_path / "also-gone"))
    assert isinstance(personnel.provider(), NullProvider)


# --- the manifest ----------------------------------------------------------


def test_manifest_parses_ids_to_slugs(tmp_path):
    root = build(tmp_path, manifest='"123": someone\n456: someone-else\n')
    p = PersonnelProvider(root)
    assert p.resolve(123) == "someone"
    assert p.resolve(456) == "someone-else"
    assert p.resolve(789) is None


def test_manifest_ignores_comments_and_blanks(tmp_path):
    manifest = '# a comment\n\n"123": someone  # trailing\n\n'
    p = PersonnelProvider(build(tmp_path, manifest=manifest))
    assert p.resolve(123) == "someone"


def test_malformed_line_is_skipped_not_fatal(tmp_path):
    manifest = 'this is not a mapping at all\n"123": someone\n'
    p = PersonnelProvider(build(tmp_path, manifest=manifest))
    assert p.resolve(123) == "someone"


def test_missing_manifest_is_not_an_error(tmp_path):
    root = tmp_path / "personnel"
    (root / "general").mkdir(parents=True)
    assert PersonnelProvider(str(root)).resolve(123) is None


@pytest.mark.parametrize("slug", ["../../.ssh", "..", "/etc/passwd", "Some_One", ""])
def test_unusable_slugs_never_resolve(tmp_path, slug):
    p = PersonnelProvider(build(tmp_path, manifest=f'"123": {slug}\n'))
    assert p.resolve(123) is None


def test_traversal_scope_reads_nothing(tmp_path):
    """Even handed a bad slug directly, no read escapes the checkout."""
    root = build(tmp_path)
    (tmp_path / "secret.md").write_text("do not read me", encoding="utf-8")
    assert PersonnelProvider(root).load_context("../..", BIG) is None


# --- reading ---------------------------------------------------------------


def test_general_reads_markdown_recursively(tmp_path):
    root = build(
        tmp_path,
        general={"a.md": "alpha", "nested/b.md": "beta", "notes.txt": "ignored"},
    )
    text = PersonnelProvider(root).load_context("general", BIG)
    assert "alpha" in text and "beta" in text
    assert "ignored" not in text


def test_manifest_is_never_injected_as_prose(tmp_path):
    root = build(tmp_path, manifest='"123": someone\n', general={"a.md": "alpha"})
    text = PersonnelProvider(root).load_context("general", BIG)
    assert "someone" not in text


def test_scaffolding_docs_are_not_context(tmp_path):
    """A fresh checkout is inert. Its READMEs describe it, they are not it."""
    root = build(
        tmp_path,
        general={"README.md": "how this directory works", "a.md": "alpha"},
        people={"someone": {"README.md": "layout notes", "n.md": "about someone"}},
    )
    p = PersonnelProvider(root)
    general = p.load_context("general", BIG)
    assert "alpha" in general and "how this directory works" not in general
    person = p.load_context("someone", BIG)
    assert "about someone" in person and "layout notes" not in person


def test_scaffold_only_checkout_injects_nothing(tmp_path):
    """The exact state the personnel scaffold ships in."""
    root = build(tmp_path, general={"README.md": "docs"}, people={"example": {"notes.md": "template"}})
    p = PersonnelProvider(root)
    assert p.load_context("general", BIG) is None
    assert p.resolve(123) is None


def test_markdown_fallback_also_skips_readme(tmp_path):
    d = tmp_path / "ctx"
    d.mkdir()
    (d / "README.md").write_text("how to use this", encoding="utf-8")
    (d / "a.md").write_text("alpha", encoding="utf-8")
    text = MarkdownProvider(str(d)).load_context("general", BIG)
    assert text == "alpha"


def test_person_scope_reads_only_that_person(tmp_path):
    root = build(
        tmp_path,
        people={"someone": {"n.md": "about someone"}, "other": {"n.md": "about other"}},
    )
    text = PersonnelProvider(root).load_context("someone", BIG)
    assert "about someone" in text
    assert "about other" not in text


def test_unknown_person_reads_nothing(tmp_path):
    assert PersonnelProvider(build(tmp_path)).load_context("nobody", BIG) is None


def test_empty_files_do_not_produce_a_block(tmp_path):
    root = build(tmp_path, general={"a.md": "   \n\n  "})
    assert PersonnelProvider(root).load_context("general", BIG) is None


def test_output_is_stable_between_reads(tmp_path):
    root = build(tmp_path, general={"a.md": "alpha", "b.md": "beta", "c.md": "gamma"})
    p = PersonnelProvider(root)
    assert p.load_context("general", BIG) == p.load_context("general", BIG)


def test_unreadable_file_is_skipped_not_fatal(tmp_path):
    root = build(tmp_path, general={"a.md": "alpha", "b.md": "beta"})
    bad = os.path.join(root, "general", "b.md")
    os.chmod(bad, 0o000)
    try:
        text = PersonnelProvider(root).load_context("general", BIG)
    finally:
        os.chmod(bad, 0o644)
    # Running as root defeats the permission bit, so assert the survivable
    # part: it returned, and what could be read came back.
    assert text is not None and "alpha" in text


# --- budget ----------------------------------------------------------------


def test_budget_truncates_rather_than_failing(tmp_path):
    root = build(tmp_path, general={"a.md": "a" * 100, "b.md": "b" * 100})
    text = PersonnelProvider(root).load_context("general", 120)
    assert "a" * 100 in text
    assert "b" * 100 not in text


def test_budget_of_zero_yields_nothing(tmp_path):
    root = build(tmp_path, general={"a.md": "alpha"})
    assert PersonnelProvider(root).load_context("general", 0) is None


# --- the plain markdown fallback -------------------------------------------


def test_markdown_single_file(tmp_path):
    path = tmp_path / "ctx.md"
    path.write_text("all the context", encoding="utf-8")
    assert MarkdownProvider(str(path)).load_context("general", BIG) == "all the context"


def test_markdown_flat_directory(tmp_path):
    d = tmp_path / "ctx"
    d.mkdir()
    (d / "a.md").write_text("alpha", encoding="utf-8")
    (d / "b.md").write_text("beta", encoding="utf-8")
    (d / "c.txt").write_text("ignored", encoding="utf-8")
    text = MarkdownProvider(str(d)).load_context("general", BIG)
    assert "alpha" in text and "beta" in text and "ignored" not in text


def test_markdown_has_no_people(tmp_path):
    """No manifest means no way to say which file is whose, so it says none."""
    d = tmp_path / "ctx"
    d.mkdir()
    (d / "someone.md").write_text("about someone", encoding="utf-8")
    provider = MarkdownProvider(str(d))
    assert provider.resolve(123) is None
    assert provider.load_context("someone", BIG) is None


# --- assembly --------------------------------------------------------------


def test_load_for_includes_header_general_and_person(
    tmp_path, monkeypatch, unresolved
):
    root = build(
        tmp_path,
        manifest='"123": someone\n',
        general={"g.md": "group history"},
        people={"someone": {"n.md": "about someone"}},
    )
    configure(monkeypatch, root)
    text = personnel.load_for({123})
    assert "group history" in text
    assert "about someone" in text
    assert "never recite" in text.lower()


def test_load_for_omits_people_who_are_not_speaking(
    tmp_path, monkeypatch, unresolved
):
    root = build(
        tmp_path,
        manifest='"123": someone\n"456": other\n',
        general={"g.md": "group history"},
        people={"someone": {"n.md": "about someone"}, "other": {"n.md": "about other"}},
    )
    configure(monkeypatch, root)
    text = personnel.load_for({123})
    assert "about someone" in text
    assert "about other" not in text


def test_load_for_spends_budget_on_general_first(tmp_path, monkeypatch, unresolved):
    """A crowded conversation must not push the shared context out."""
    import config

    root = build(
        tmp_path,
        manifest='"123": someone\n',
        general={"g.md": "g" * 200},
        people={"someone": {"n.md": "p" * 200}},
    )
    configure(monkeypatch, root)
    monkeypatch.setattr(config, "CONTEXT_MAX_CHARS", 250)
    text = personnel.load_for({123})
    assert "g" * 200 in text
    assert "p" * 200 not in text


def test_load_for_with_no_speakers_still_gives_general(
    tmp_path, monkeypatch, unresolved
):
    root = build(tmp_path, general={"g.md": "group history"})
    configure(monkeypatch, root)
    assert "group history" in personnel.load_for(set())


def test_load_for_empty_checkout_is_empty_string(tmp_path, monkeypatch, unresolved):
    configure(monkeypatch, build(tmp_path))
    assert personnel.load_for({123}) == ""
