"""Validate proposals and render private examples with the actual Fluent engine."""

import re
import unicodedata

from babel import Locale
from babel.core import UnknownLocaleError
from fluent.runtime import FluentBundle, FluentResource
from fluent.syntax import ast

from ..messages.localization import Localization
from .catalog import PARSER
from .models import MAX_TEXT, TranslationError, Unit

PLACEHOLDER = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')


def clean_text(value, *, limit=MAX_TEXT, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise TranslationError('translation-error-text', limit=limit)
    if any(unicodedata.category(char) == 'Cc' and char not in '\n\r\t' for char in value):
        raise TranslationError('translation-error-text', limit=limit)
    return value.replace('\r\n', '\n').replace('\r', '\n')


def language_code(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8}){0,2}', value):
        raise TranslationError('translation-error-language')
    value = value.lower()
    try:
        locale = Locale.parse(value, sep='-')
    except (ValueError, UnknownLocaleError):
        raise TranslationError('translation-error-language') from None
    return str(locale).replace('_', '-').lower()


def nodes(value):
    yield value
    if isinstance(value, ast.BaseNode):
        for key, child in vars(value).items():
            if key != 'span':
                yield from nodes(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from nodes(child)


def parse(unit: Unit, value: str):
    resource = PARSER.parse(unit.key + ' = ' + value + '\n')
    entries = [entry for entry in resource.body if isinstance(entry, (ast.Message, ast.Term))]
    if len(entries) != 1 or any(isinstance(entry, ast.Junk) for entry in resource.body):
        raise TranslationError('translation-error-format')
    return entries[0]


def structure(node):
    return {
        'variables': {n.id.name for n in nodes(node) if isinstance(n, ast.VariableReference)},
        'messages': {(n.id.name, n.attribute.name if n.attribute else '') for n in nodes(node) if isinstance(n, ast.MessageReference)},
        'terms': {(n.id.name, n.attribute.name if n.attribute else '') for n in nodes(node) if isinstance(n, ast.TermReference)},
        'functions': {n.id.name for n in nodes(node) if isinstance(n, ast.FunctionReference)},
        'attributes': {n.id.name for n in node.attributes},
    }


def validate(unit: Unit, value: str) -> str:
    value = clean_text(value)
    if unit.kind == 'fluent':
        original, translated = parse(unit, unit.original), parse(unit, value)
        source, target = structure(original), structure(translated)
        if source['variables'] != target['variables']:
            raise TranslationError('translation-error-variables', variables=', '.join(sorted(source['variables'])) or '—')
        if any(source[key] != target[key] for key in ('messages', 'terms', 'functions', 'attributes')):
            raise TranslationError('translation-error-references')
        source_selects = [n for n in nodes(original) if isinstance(n, ast.SelectExpression)]
        target_selects = [n for n in nodes(translated) if isinstance(n, ast.SelectExpression)]
        if len(source_selects) != len(target_selects):
            raise TranslationError('translation-error-variants')
        for source_select, target_select in zip(source_selects, target_selects):
            source_keys = {str(v.key.name if isinstance(v.key, ast.Identifier) else v.key.value) for v in source_select.variants}
            target_keys = {str(v.key.name if isinstance(v.key, ast.Identifier) else v.key.value) for v in target_select.variants}
            if not source_keys <= target_keys or sum(v.default for v in target_select.variants) != 1:
                raise TranslationError('translation-error-variants')
    elif unit.kind == 'text' and set(PLACEHOLDER.findall(unit.original)) != set(PLACEHOLDER.findall(value)):
        raise TranslationError('translation-error-variables', variables=', '.join(sorted(set(PLACEHOLDER.findall(unit.original)))) or '—')
    return value


def example(unit: Unit, value: str, language: str, *, variant='other', resources=None) -> str:
    value = validate(unit, value)
    if unit.kind == 'markdown':
        return value
    if unit.kind == 'text':
        return PLACEHOLDER.sub(lambda match: 'Alex' if any(word in match[1].lower() for word in ('player', 'name', 'user', 'author')) else '2', value)
    node = parse(unit, value)
    arguments = {}
    for variable in structure(node)['variables']:
        name = variable.lower()
        arguments[variable] = variant if 'gender' in name else 'Alex' if any(word in name for word in ('player', 'user', 'author', 'name', 'host', 'target')) else 2
    # Common enum selectors should exercise the requested form, not a number.
    for select in (n for n in nodes(node) if isinstance(n, ast.SelectExpression)):
        if isinstance(select.selector, ast.VariableReference):
            keys = [v.key.name for v in select.variants if isinstance(v.key, ast.Identifier)]
            if variant in keys and variant not in {'one', 'two', 'few', 'many', 'other', 'zero'}:
                arguments[select.selector.id.name] = variant
    bundle = FluentBundle([language], use_isolating=False,
                          functions={'GENDER_TERM': lambda gender, form, context='': Localization._format_gender_term(language, gender, form, context)})
    # Unresolved trusted references are reported as such; never substitute a
    # misleading successful preview or execute user-provided functions.
    for key, dependency in (resources or {}).items():
        if key != unit.key:
            bundle.add_resource(FluentResource(key + ' = ' + dependency))
    bundle.add_resource(FluentResource(unit.key + ' = ' + value))
    if unit.key.startswith('-'):
        return value
    message = bundle.get_message(unit.key)
    if message.value is None:
        return value
    rendered, errors = bundle.format_pattern(message.value, arguments)
    if errors:
        raise TranslationError('translation-error-preview')
    return rendered
