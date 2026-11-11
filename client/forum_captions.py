"""Bounded plain-text WebVTT cues for the native video viewer."""

import html
import re

_TIME = re.compile(r'(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})\Z')


def timestamp(value: str) -> float:
    match = _TIME.fullmatch(value)
    if not match:
        raise ValueError('Invalid caption time')
    hours, minutes, seconds, millis = (int(part or 0) for part in match.groups())
    if minutes >= 60 or seconds >= 60:
        raise ValueError('Invalid caption time')
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def parse_captions(content: bytes) -> list[tuple[float, float, str]]:
    if len(content) > 2 * 1024 * 1024:
        raise ValueError('Captions exceed size limit')
    value = content.decode('utf-8-sig').replace('\r\n', '\n')
    if not value.startswith('WEBVTT'):
        raise ValueError('Invalid caption format')
    cues = []
    for block in re.split(r'\n\s*\n', value):
        lines = block.splitlines()
        if not lines or lines[0].startswith(('NOTE', 'STYLE', 'REGION')):
            continue
        for index, line in enumerate(lines):
            if ' --> ' not in line:
                continue
            start_text, end_text = line.split(' --> ', 1)
            start, end = timestamp(start_text.strip()), timestamp(end_text.split()[0])
            if end <= start:
                raise ValueError('Invalid caption interval')
            text = html.unescape(re.sub(r'<[^>]*>', '', '\n'.join(lines[index + 1:])))
            text = text[:1000] + ('…' if len(text) > 1000 else '')
            if text:
                cues.append((start, end, text))
            break
        if len(cues) > 5000:
            raise ValueError('Too many caption cues')
    return sorted(cues)


def captions_at(cues, seconds: float) -> str:
    return '\n'.join(text for start, end, text in cues if start <= seconds < end)[:2000]
