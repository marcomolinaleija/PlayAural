"""Packaged source identity for updates whose protocol version is unchanged."""
from collections.abc import Mapping
import json
from pathlib import Path
import re
import sys


BUILD_ID = re.compile(r'^[0-9a-f]{40}$')


def get_build_id(path=None):
    if path is None and not getattr(sys, 'frozen', False):
        return ''
    path = Path(path) if path is not None else Path(__file__).with_name('release-build.json')
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ''
    value = record.get('source_commit') if isinstance(record, dict) else None
    return value if isinstance(value, str) and BUILD_ID.fullmatch(value) else ''


def application_update_required(info, current_version, *, current_build=None, packaged=None):
    if not isinstance(info, Mapping):
        return False
    version = info.get('version')
    if not isinstance(version, str) or not version:
        return False
    if version != current_version:
        return True
    expected = info.get('build_id')
    if not isinstance(expected, str) or not BUILD_ID.fullmatch(expected):
        return False
    current = get_build_id() if current_build is None else current_build
    frozen = bool(getattr(sys, 'frozen', False)) if packaged is None else packaged
    return bool(current or frozen) and expected != current
