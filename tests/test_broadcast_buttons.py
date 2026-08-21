from types import SimpleNamespace

from bot.handlers.delivery import _parse_inline_button, _reply_content


def test_inline_button_accepts_quoted_and_unquoted_labels() -> None:
    assert _parse_inline_button('"Open Course" https://example.com/course') == {
        "text": "Open Course", "url": "https://example.com/course",
    }
    assert _parse_inline_button("Open Course https://example.com/course") == {
        "text": "Open Course", "url": "https://example.com/course",
    }


def test_inline_button_rejects_invalid_links() -> None:
    assert _parse_inline_button("Open javascript:alert(1)") is None
    assert _parse_inline_button("Open ftp://example.com") is None
    assert _parse_inline_button("https://example.com") is None


def test_reply_content_supports_text_photo_video_and_quiz_poll() -> None:
    text = _reply_content(SimpleNamespace(text="Study now", photo=None, video=None, poll=None))
    assert text == ("text", "Study now", {})

    photo = _reply_content(SimpleNamespace(text=None, caption="Photo caption", photo=[SimpleNamespace(file_id="photo-id")], video=None, poll=None))
    assert photo == ("photo", "Photo caption", {"file_id": "photo-id"})

    video = _reply_content(SimpleNamespace(text=None, caption="Video caption", photo=None, video=SimpleNamespace(file_id="video-id"), poll=None))
    assert video == ("video", "Video caption", {"file_id": "video-id"})

    poll = _reply_content(SimpleNamespace(
        text=None, caption=None, photo=None, video=None,
        chat_id=-123, message_id=45,
        poll=SimpleNamespace(type="quiz", question="Q?", options=[SimpleNamespace(text="A")], correct_option_id=0),
    ))
    assert poll and poll[0] == "poll" and poll[2]["source_message_id"] == 45
