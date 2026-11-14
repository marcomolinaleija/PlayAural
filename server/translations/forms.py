"""Present Fluent alternatives as ordinary text fields, preserving their layout."""

from dataclasses import dataclass, replace

from fluent.syntax import ast

from .models import Unit
from .validation import parse, validate


@dataclass(frozen=True)
class Form:
    id: str
    value: str
    start: int
    end: int


def forms(unit: Unit, value: str | None = None) -> list[Form]:
    if unit.kind != 'fluent':
        return []
    value = unit.original if value is None else value
    prefix = unit.key + ' = '
    raw = prefix + value + '\n'
    node = parse(unit, value)
    result = []

    def walk(pattern, path):
        selects = [element for element in pattern.elements
                   if isinstance(element, ast.Placeable) and isinstance(element.expression, ast.SelectExpression)]
        if not selects:
            result.append(Form(path, raw[pattern.span.start:pattern.span.end],
                               pattern.span.start - len(prefix), pattern.span.end - len(prefix)))
            return
        ordinary = []
        part = 0
        for element in pattern.elements:
            if isinstance(element, ast.Placeable) and isinstance(element.expression, ast.SelectExpression):
                if ordinary:
                    start, end = ordinary[0].span.start, ordinary[-1].span.end
                    if raw[start:end].strip():
                        result.append(Form(path + '/part:' + str(part), raw[start:end], start - len(prefix), end - len(prefix)))
                    ordinary = []
                for variant in element.expression.variants:
                    key = variant.key.name if isinstance(variant.key, ast.Identifier) else variant.key.value
                    walk(variant.value, path + '/case:' + str(part) + ':' + str(key))
                part += 1
            else:
                ordinary.append(element)
        if ordinary:
            start, end = ordinary[0].span.start, ordinary[-1].span.end
            if raw[start:end].strip():
                result.append(Form(path + '/part:' + str(part), raw[start:end], start - len(prefix), end - len(prefix)))

    if node.value is not None:
        walk(node.value, 'text')
    for attribute in node.attributes:
        walk(attribute.value, 'attribute:' + attribute.id.name)
    return result


def needs_forms(unit: Unit):
    return unit.kind == 'fluent' and (len(forms(unit)) > 1 or any(form.id != 'text' for form in forms(unit)))


def form_unit(unit: Unit, form: Form):
    return replace(unit, key='preview', original=form.value)


def assemble(unit: Unit, values: dict[str, str], *, validate_fields=False):
    value = unit.original
    for form in sorted(forms(unit), key=lambda form: form.start, reverse=True):
        if form.id in values:
            translated = values[form.id]
            if validate_fields:
                validate(form_unit(unit, form), translated)
            # Fluent continuation text must stay indented. The surrounding
            # trusted selector/attribute syntax is never editable by authors.
            indent = ' ' * (form.start - (unit.original.rfind('\n', 0, form.start) + 1))
            translated = translated.replace('\n', '\n' + (indent if indent else '    '))
            value = value[:form.start] + translated + value[form.end:]
    return value
