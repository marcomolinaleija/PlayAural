"""Word pairs and word manager for Infiltrado game."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
from pathlib import Path
import random
import unicodedata

logger = logging.getLogger(__name__)

WORDS_JSON_PATH = Path(__file__).parent / "words.json"


@dataclass
class WordPair:
    """A pair of related words for the Infiltrado game."""

    id: int
    word1: str
    word2: str
    clues_word1: list[str] = field(default_factory=list)
    clues_word2: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> WordPair:
        return cls(
            id=int(data.get("id", 0)),
            word1=str(data.get("word1", "")).strip(),
            word2=str(data.get("word2", "")).strip(),
            clues_word1=list(data.get("clues_word1", [])),
            clues_word2=list(data.get("clues_word2", [])),
        )


def normalize_word(text: str) -> str:
    """Normalize word for comparison: stripped, lowercased, accent-folded."""
    if not text:
        return ""
    norm = unicodedata.normalize("NFD", text.strip().lower())
    return "".join(c for c in norm if unicodedata.category(c) != "Mn")


class InfiltradoWordManager:
    """Thread-safe word pair repository with JSON persistence."""

    _pairs: list[WordPair] = []
    _loaded: bool = False

    @classmethod
    def get_json_path(cls) -> Path:
        return WORDS_JSON_PATH

    @classmethod
    def reload(cls) -> list[WordPair]:
        cls._pairs = cls._load_from_disk()
        cls._loaded = True
        return cls._pairs

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls._loaded:
            cls.reload()

    @classmethod
    def _load_from_disk(cls) -> list[WordPair]:
        path = cls.get_json_path()
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                return [WordPair.from_dict(item) for item in raw if isinstance(item, dict)]
        except Exception as exc:
            logger.error("Error loading infiltrado words from %s: %s", path, exc)
        return []

    @classmethod
    def _save_to_disk(cls) -> None:
        path = cls.get_json_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump([p.to_dict() for p in cls._pairs], f, ensure_ascii=False, indent=2)
            temp_path.replace(path)
        except Exception as exc:
            logger.error("Error saving infiltrado words to %s: %s", path, exc)
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

    @classmethod
    def get_all_pairs(cls) -> list[WordPair]:
        cls._ensure_loaded()
        return list(cls._pairs)

    @classmethod
    def count_pairs(cls) -> int:
        cls._ensure_loaded()
        return len(cls._pairs)

    @classmethod
    def get_pair_by_id(cls, pair_id: int) -> WordPair | None:
        cls._ensure_loaded()
        for p in cls._pairs:
            if p.id == pair_id:
                return p
        return None

    @classmethod
    def get_random_pair(cls) -> WordPair | None:
        cls._ensure_loaded()
        if not cls._pairs:
            return None
        return random.choice(cls._pairs)

    @classmethod
    def add_pair(
        cls,
        word1: str,
        word2: str,
        clues_word1: list[str] | None = None,
        clues_word2: list[str] | None = None,
    ) -> WordPair:
        cls._ensure_loaded()
        next_id = max((p.id for p in cls._pairs), default=0) + 1
        new_pair = WordPair(
            id=next_id,
            word1=word1.strip(),
            word2=word2.strip(),
            clues_word1=clues_word1 or [],
            clues_word2=clues_word2 or [],
        )
        cls._pairs.append(new_pair)
        cls._save_to_disk()
        return new_pair

    @classmethod
    def update_pair(
        cls,
        pair_id: int,
        word1: str | None = None,
        word2: str | None = None,
        clues_word1: list[str] | None = None,
        clues_word2: list[str] | None = None,
    ) -> WordPair | None:
        cls._ensure_loaded()
        for idx, p in enumerate(cls._pairs):
            if p.id == pair_id:
                updated = WordPair(
                    id=p.id,
                    word1=word1.strip() if word1 is not None else p.word1,
                    word2=word2.strip() if word2 is not None else p.word2,
                    clues_word1=clues_word1 if clues_word1 is not None else p.clues_word1,
                    clues_word2=clues_word2 if clues_word2 is not None else p.clues_word2,
                )
                cls._pairs[idx] = updated
                cls._save_to_disk()
                return updated
        return None

    @classmethod
    def delete_pair(cls, pair_id: int) -> bool:
        cls._ensure_loaded()
        initial_len = len(cls._pairs)
        cls._pairs = [p for p in cls._pairs if p.id != pair_id]
        if len(cls._pairs) != initial_len:
            cls._save_to_disk()
            return True
        return False
