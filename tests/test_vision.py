"""Looking at what people send.

He read `clean_content` and nothing else, so an attachment was invisible: a
picture with a caption arrived as the caption alone, and a picture with no
caption arrived empty and was dropped before anything looked at it. Someone
sending a screenshot and asking "what do you make of this" was talking to
something that could not see it.
"""

from __future__ import annotations

import asyncio
import types

import pytest

import vision


def _attachment(filename="a.png", content_type="image/png", size=1000, url="http://x/a"):
    return types.SimpleNamespace(
        filename=filename, content_type=content_type, size=size, url=url
    )


# --- what counts as an image ------------------------------------------------


@pytest.mark.parametrize(
    "declared,name,expected",
    [
        ("image/png", "a.png", "image/png"),
        ("image/jpeg", "a.jpg", "image/jpeg"),
        ("image/gif", "a.gif", "image/gif"),
        ("image/webp", "a.webp", "image/webp"),
        # Discord sometimes serves a bare octet-stream for a plain png.
        ("application/octet-stream", "screenshot.PNG", "image/png"),
        ("", "photo.jpeg", "image/jpeg"),
        ("image/png; charset=binary", "a.png", "image/png"),
    ],
)
def test_images_are_recognised(declared, name, expected):
    assert vision.media_type(_attachment(name, declared)) == expected


@pytest.mark.parametrize(
    "declared,name",
    [
        ("image/bmp", "a.bmp"),
        ("image/tiff", "a.tiff"),
        ("application/pdf", "report.pdf"),
        ("text/plain", "log.txt"),
        ("video/mp4", "clip.mp4"),
        ("", "unknown"),
    ],
)
def test_other_files_are_not_images(declared, name):
    """Sending an unsupported type is a 400, not a degraded answer."""
    assert vision.media_type(_attachment(name, declared)) is None


def test_a_huge_file_is_skipped():
    """A 20MB screenshot costs latency for detail that resizing discards."""
    assert vision.too_big(_attachment(size=vision.MAX_BYTES + 1)) is True
    assert vision.too_big(_attachment(size=vision.MAX_BYTES)) is False


def test_an_oversized_image_is_not_fetched():
    assert asyncio.run(vision.fetch(_attachment(size=99 * 1024 * 1024))) is None


def test_a_non_image_is_not_fetched():
    assert asyncio.run(vision.fetch(_attachment("report.pdf", "application/pdf"))) is None


def test_a_missing_url_is_survivable():
    assert asyncio.run(vision.fetch(_attachment(url=""))) is None


# --- naming what was sent ---------------------------------------------------


def test_attachments_are_named_in_the_transcript():
    """An uncaptioned image used to render as a blank transcript line."""
    message = types.SimpleNamespace(attachments=[_attachment("evidence.png")])
    assert vision.describes_attachments(message) == "[attached: evidence.png]"


def test_several_attachments_are_all_named():
    message = types.SimpleNamespace(
        attachments=[_attachment("a.png"), _attachment("b.jpg")]
    )
    assert "a.png, b.jpg" in vision.describes_attachments(message)


def test_no_attachments_adds_nothing():
    assert vision.describes_attachments(types.SimpleNamespace(attachments=[])) == ""
    assert vision.describes_attachments(types.SimpleNamespace()) == ""


# --- the content block ------------------------------------------------------


def test_images_lead_the_user_turn(bot_module):
    """The API reads a picture better when the question comes after it, and
    this is nearly always "here is a thing, what do you make of it"."""
    blocks = bot_module._with_images("what is this", [{"type": "image"}])
    assert blocks[0]["type"] == "image"
    assert blocks[-1] == {"type": "text", "text": "what is this"}


def test_no_images_leaves_a_plain_string(bot_module):
    """Every other call in the codebase passes a string; do not change that
    shape for the overwhelming majority of messages that carry no picture."""
    assert bot_module._with_images("just talking", []) == "just talking"
    assert bot_module._with_images("just talking", None) == "just talking"


# --- the forensic instruction -----------------------------------------------


def test_the_dm_framing_asks_for_examination_not_reaction():
    import prompts

    body = prompts.DM_FRAMING
    assert "Actually examine it" in body
    assert "what you observed, then what you infer" in body
