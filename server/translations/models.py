"""Bounded translation records and user-facing domain failures."""

from dataclasses import dataclass
import hashlib

MAX_TEXT = 64000
MAX_NOTE = 1000
MAX_OPEN_PROPOSALS = 1000
MAX_BATCH = 100
PAGE_SIZE = 30
OPEN_STATES = ('draft', 'pending', 'changes_requested')
FINAL_STATES = ('approved', 'rejected', 'withdrawn', 'reverted')


class TranslationError(ValueError):
    def __init__(self, key: str, **values):
        self.key, self.values = key, values
        super().__init__(key)


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class Unit:
    id: str
    domain: str
    path: str
    key: str
    original: str
    source_locale: str
    kind: str
    section: str

    @property
    def source_hash(self):
        return fingerprint(self.original)
