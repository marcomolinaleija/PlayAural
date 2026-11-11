"""Bounded readable subtitles for native playback, without HTML rendering."""

import pytest

from forum_captions import captions_at, parse_captions


def test_captions_preserve_plain_text_timing_and_overlap_without_markup():
    cues = parse_captions(b'WEBVTT\n\nfirst\n00:00:01.000 --> 00:00:03.000 align:center\n<v Alice>Hello &amp; welcome</v>\n\n00:02.000 --> 00:04.000\nSecond cue\n')
    assert captions_at(cues, 0.9) == ''
    assert captions_at(cues, 1) == 'Hello & welcome'
    assert captions_at(cues, 2.5) == 'Hello & welcome\nSecond cue'
    assert captions_at(cues, 3) == 'Second cue'
    assert captions_at(cues, 4) == ''


@pytest.mark.parametrize('content', [b'<html>untrusted</html>', b'WEBVTT\n\n00:70.000 --> 00:71.000\nWrong time',
                                     b'WEBVTT\n\n00:02.000 --> 00:01.000\nReverse time'])
def test_invalid_or_non_caption_content_is_rejected(content):
    with pytest.raises(ValueError):
        parse_captions(content)


def test_caption_work_is_bounded_and_metadata_blocks_do_not_become_speech():
    cues = parse_captions(('WEBVTT\n\nNOTE private note\nNot a cue\n\n00:00.000 --> 00:01.000\n' + 'A' * 5000).encode())
    assert len(captions_at(cues, 0)) == 1001
    with pytest.raises(ValueError):
        parse_captions(b'A' * (2 * 1024 * 1024 + 1))
