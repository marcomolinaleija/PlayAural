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
DEFAULT_CATEGORY = "General"


@dataclass
class WordPair:
    """A pair of related words for the Infiltrado game."""

    id: int
    word1: str
    word2: str
    category: str = DEFAULT_CATEGORY
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
            category=str(data.get("category", DEFAULT_CATEGORY)).strip() or DEFAULT_CATEGORY,
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
    _categories: list[str] = []
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
            cls._categories = [DEFAULT_CATEGORY]
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                pairs = [WordPair.from_dict(item) for item in raw if isinstance(item, dict)]
                cats = sorted({p.category for p in pairs if p.category})
                if DEFAULT_CATEGORY not in cats:
                    cats.insert(0, DEFAULT_CATEGORY)
                cls._categories = cats
                return pairs
            elif isinstance(raw, dict):
                pairs = [
                    WordPair.from_dict(item)
                    for item in raw.get("pairs", [])
                    if isinstance(item, dict)
                ]
                cats = list(raw.get("categories", []))
                for p in pairs:
                    if p.category and p.category not in cats:
                        cats.append(p.category)
                if DEFAULT_CATEGORY not in cats:
                    cats.insert(0, DEFAULT_CATEGORY)
                cls._categories = cats
                return pairs
        except Exception as exc:
            logger.error("Error loading infiltrado words from %s: %s", path, exc)
            cls._categories = [DEFAULT_CATEGORY]
        return []

    @classmethod
    def _save_to_disk(cls) -> None:
        path = cls.get_json_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        try:
            payload = {
                "categories": cls._categories,
                "pairs": [p.to_dict() for p in cls._pairs],
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            temp_path.replace(path)
        except Exception as exc:
            logger.error("Error saving infiltrado words to %s: %s", path, exc)
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

    @classmethod
    def get_categories(cls) -> list[str]:
        cls._ensure_loaded()
        return list(cls._categories)

    @classmethod
    def add_category(cls, name: str) -> bool:
        cls._ensure_loaded()
        clean = name.strip()
        if not clean:
            return False
        if any(c.lower() == clean.lower() for c in cls._categories):
            return False
        cls._categories.append(clean)
        cls._save_to_disk()
        return True

    @classmethod
    def rename_category(cls, old_name: str, new_name: str) -> bool:
        cls._ensure_loaded()
        clean_new = new_name.strip()
        if not clean_new or old_name.lower() == clean_new.lower():
            return False
        found_idx = None
        for idx, c in enumerate(cls._categories):
            if c.lower() == old_name.lower():
                found_idx = idx
                break
        if found_idx is None:
            return False
        cls._categories[found_idx] = clean_new
        for idx, p in enumerate(cls._pairs):
            if p.category.lower() == old_name.lower():
                cls._pairs[idx] = WordPair(
                    id=p.id,
                    word1=p.word1,
                    word2=p.word2,
                    category=clean_new,
                    clues_word1=p.clues_word1,
                    clues_word2=p.clues_word2,
                )
        cls._save_to_disk()
        return True

    @classmethod
    def delete_category(cls, name: str, reassign_to: str = DEFAULT_CATEGORY) -> bool:
        cls._ensure_loaded()
        if name.lower() == reassign_to.lower() or name.lower() == DEFAULT_CATEGORY.lower():
            return False
        found_idx = None
        for idx, c in enumerate(cls._categories):
            if c.lower() == name.lower():
                found_idx = idx
                break
        if found_idx is None:
            return False
        cls._categories.pop(found_idx)
        if not any(c.lower() == reassign_to.lower() for c in cls._categories):
            cls._categories.insert(0, reassign_to)
        for idx, p in enumerate(cls._pairs):
            if p.category.lower() == name.lower():
                cls._pairs[idx] = WordPair(
                    id=p.id,
                    word1=p.word1,
                    word2=p.word2,
                    category=reassign_to,
                    clues_word1=p.clues_word1,
                    clues_word2=p.clues_word2,
                )
        cls._save_to_disk()
        return True

    @classmethod
    def get_pairs_by_category(cls, category: str | None = None) -> list[WordPair]:
        cls._ensure_loaded()
        if not category or category.lower() in ("all", "todas"):
            return list(cls._pairs)
        return [p for p in cls._pairs if p.category.lower() == category.lower()]

    @classmethod
    def count_pairs_by_category(cls, category: str | None = None) -> int:
        return len(cls.get_pairs_by_category(category))

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
    def get_random_pair(cls, category: str | None = None) -> WordPair | None:
        cls._ensure_loaded()
        if category and category.lower() not in ("all", "todas"):
            candidates = cls.get_pairs_by_category(category)
            if candidates:
                return random.choice(candidates)
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
        category: str = DEFAULT_CATEGORY,
    ) -> WordPair:
        cls._ensure_loaded()
        clean_cat = category.strip() or DEFAULT_CATEGORY
        if not any(c.lower() == clean_cat.lower() for c in cls._categories):
            cls._categories.append(clean_cat)
        next_id = max((p.id for p in cls._pairs), default=0) + 1
        new_pair = WordPair(
            id=next_id,
            word1=word1.strip(),
            word2=word2.strip(),
            category=clean_cat,
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
        category: str | None = None,
        clues_word1: list[str] | None = None,
        clues_word2: list[str] | None = None,
    ) -> WordPair | None:
        cls._ensure_loaded()
        clean_cat = category.strip() if category is not None else None
        if clean_cat and not any(c.lower() == clean_cat.lower() for c in cls._categories):
            cls._categories.append(clean_cat)
        for idx, p in enumerate(cls._pairs):
            if p.id == pair_id:
                updated = WordPair(
                    id=p.id,
                    word1=word1.strip() if word1 is not None else p.word1,
                    word2=word2.strip() if word2 is not None else p.word2,
                    category=clean_cat if clean_cat is not None else p.category,
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

