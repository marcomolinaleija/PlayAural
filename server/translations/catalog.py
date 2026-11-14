"""Trusted on-disk catalog, independent of user proposals and filesystem writes."""

import json
from functools import lru_cache
from pathlib import Path
import re

from fluent.syntax import FluentParser, ast

from .models import TranslationError, Unit, fingerprint

ROOT = Path(__file__).resolve().parents[2]
DOMAINS = ('server', 'windows', 'web', 'android', 'documentation')
PARSER = FluentParser(with_spans=True)


def read_web_object(text: str) -> dict:
    """Read the existing literal module format without executing JavaScript."""
    text = text.removeprefix('\ufeff').strip()
    if not text.startswith('export default '):
        raise ValueError('Expected a literal locale module')
    text = text[len('export default '):].rstrip('; \r\n')
    result, index, quoted, escaped = [], 0, False, False
    while index < len(text):
        char = text[index]
        if quoted:
            result.append(char)
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
            result.append(char)
        elif text[index:index + 2] == '//':
            end = text.find('\n', index)
            index = len(text) if end < 0 else end
            continue
        elif text[index:index + 2] == '/*':
            end = text.find('*/', index + 2)
            if end < 0:
                raise ValueError('Unclosed locale comment')
            index = end + 2
            continue
        elif char == ',' and text[index + 1:].lstrip().startswith(('}', ']')):
            pass
        else:
            result.append(char)
        index += 1
    value = json.loads(''.join(result))
    if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
        raise ValueError('Locale modules must contain string pairs')
    return value


def fluent_messages(text: str) -> dict[str, str]:
    values = {}
    for entry in PARSER.parse(text).body:
        if isinstance(entry, (ast.Message, ast.Term)):
            key = ('-' if isinstance(entry, ast.Term) else '') + entry.id.name
            raw = text[entry.span.start:entry.span.end]
            # Comments belong to the context, never to an editable translation.
            match = re.search(r'^' + re.escape(key) + r'\s*= ?', raw, re.MULTILINE)
            if match:
                values[key] = raw[match.end():].rstrip()
    return values


class Catalog:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self.units: dict[str, Unit] = {}
        self._files: dict[tuple[str, str, str], dict[str, str]] = {}
        self._metadata = None
        self._build()

    def directory(self, domain: str, language: str) -> Path:
        return {
            'server': self.root / 'server/locales' / language,
            'windows': self.root / 'client/locales' / language,
            'web': self.root / 'web_client/locales',
            'android': self.root / 'mobile_client/locales' / language,
            'documentation': self.root / 'server/documentation/content' / language,
        }[domain]

    def paths(self, domain: str, language: str):
        directory = self.directory(domain, language)
        if domain == 'server':
            return sorted(p.name for p in directory.glob('*.ftl'))
        if domain == 'documentation':
            return sorted(p.relative_to(directory).as_posix() for p in directory.rglob('*.md'))
        return ['client.ftl' if domain == 'windows' else 'client.json' if domain == 'android' else 'catalog.js']

    def file_path(self, domain: str, path: str, language: str) -> Path:
        return self.directory(domain, language) / (language + '.js' if domain == 'web' else path)

    def values(self, domain: str, path: str, language: str):
        cache_key = domain, path, language
        if cache_key not in self._files:
            file = self.file_path(domain, path, language)
            if not file.is_file():
                values = {}
            else:
                text = file.read_text(encoding='utf-8-sig')
                if domain in {'server', 'windows'}:
                    values = fluent_messages(text)
                elif domain == 'web':
                    values = read_web_object(text)
                elif domain == 'android':
                    values = json.loads(text)
                else:
                    values = {'document': text}
            self._files[cache_key] = values
        return self._files[cache_key]

    def _build(self):
        for domain in DOMAINS:
            for path in sorted(set(self.paths(domain, 'es')) | set(self.paths(domain, 'en'))):
                originals = {}
                for locale in ('en', 'es'):
                    originals.update({key: (value, locale) for key, value in self.values(domain, path, locale).items()})
                for key, (value, locale) in originals.items():
                    unit_id = fingerprint('\0'.join((domain, path, key)))[:32]
                    kind = 'fluent' if domain in {'server', 'windows'} else 'markdown' if domain == 'documentation' else 'text'
                    self.units[unit_id] = Unit(unit_id, domain, path, key, value, locale, kind,
                                               domain + ':' + Path(path).stem)

    def get(self, unit_id: str) -> Unit:
        if unit_id not in self.units:
            raise TranslationError('translation-error-unit')
        return self.units[unit_id]

    def current(self, unit: Unit, language: str) -> str:
        if unit.id in self.languages().get(language, {}).get('fallback_units', []):
            return ''
        return self.values(unit.domain, unit.path, language).get(unit.key, '')

    def languages(self):
        if self._metadata is not None:
            return self._metadata
        result = {}
        for path in sorted((self.root / 'server/locales').glob('*/metadata.json')):
            metadata = json.loads(path.read_text(encoding='utf-8-sig'))
            result[metadata['code']] = metadata
        self._metadata = result
        return result


@lru_cache(maxsize=1)
def default_catalog():
    return Catalog()
