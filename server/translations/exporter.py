"""Create a checksummed release bundle from an immutable reviewed snapshot."""

from collections import defaultdict
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile
from fluent.syntax import ast

from babel import Locale

from .catalog import PARSER
from .models import TranslationError, fingerprint
from .validation import language_code, validate, parse, structure


def snapshot(service, reviewer):
    """Capture on SQLite's owner loop before any filesystem work is dispatched."""
    service.roles.require_admin(reviewer)
    languages = service.languages(reviewer)
    result = {'languages': {}, 'entries': []}
    for row in service.connection.execute('SELECT * FROM translation_accepted ORDER BY language, unit_id'):
        if not row['value']:
            continue  # A reverted, originally missing entry must still fall back.
        unit = service.catalog.get(row['unit_id'])
        if row['source_hash'] != unit.source_hash:
            raise TranslationError('translation-error-source-changed')
        validate(unit, row['value'])
        code = language_code(row['language'])
        result['entries'].append({'language': code, 'unit_id': unit.id, 'domain': unit.domain,
                                  'path': unit.path, 'key': unit.key, 'value': row['value'],
                                  'source_hash': unit.source_hash, 'revision': row['revision']})
        result['languages'][code] = {key: languages[code][key] for key in ('name', 'native_name')}
        result['languages'][code]['contributors'] = [person['username'] for person in service.credits(reviewer, code)]
    return result


def replace_fluent(text, translations):
    replacements = []
    found = set()
    for entry in PARSER.parse(text).body:
        if not hasattr(entry, 'id'):
            continue
        name = ('-' if isinstance(entry, ast.Term) else '') + entry.id.name
        if name not in translations:
            continue
        raw = text[entry.span.start:entry.span.end]
        start = re.search(r'^' + re.escape(name) + r'\s*=', raw, re.MULTILINE)
        if start is None:
            continue
        found.add(name)
        replacements.append((entry.span.start + start.start(), entry.span.end, name + ' = ' + translations[name]))
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    for name in sorted(set(translations) - found):
        text = text.rstrip() + '\n\n' + name + ' = ' + translations[name] + '\n'
    return text.lstrip('\n')


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def grouped_values(data, catalog):
    grouped = defaultdict(dict)
    for entry in data['entries']:
        unit = catalog.get(entry['unit_id'])
        if (entry['domain'], entry['path'], entry['key'], entry['source_hash']) != (unit.domain, unit.path, unit.key, unit.source_hash):
            raise TranslationError('translation-error-source-changed')
        validate(unit, entry['value'])
        code = language_code(entry['language'])
        grouped[code, unit.domain, unit.path][unit.key] = entry['value']
    index = {(unit.domain, unit.key): unit for unit in catalog.units.values() if unit.kind == 'fluent'}
    pending = [(entry['language'], catalog.get(entry['unit_id']), entry['value']) for entry in data['entries'] if catalog.get(entry['unit_id']).kind == 'fluent']
    visited, dependencies = set(), []
    while pending:
        code, unit, value = pending.pop()
        if (code, unit.id) in visited:
            continue
        visited.add((code, unit.id))
        info = structure(parse(unit, value))
        keys = {key for key, _ in info['messages']} | {'-' + key for key, _ in info['terms']}
        for key in keys:
            dependency = index.get((unit.domain, key))
            if dependency is None or catalog.current(dependency, code):
                continue
            translations = grouped[code, dependency.domain, dependency.path]
            if key not in translations:
                translations[key] = catalog.values(dependency.domain, dependency.path, 'en').get(key, dependency.original)
                dependencies.append({'language': code, 'unit_id': dependency.id, 'source_hash': dependency.source_hash})
            pending.append((code, dependency, translations[key]))
    return grouped, dependencies


def build_files(data, catalog):
    grouped, dependencies = grouped_values(data, catalog)
    files = {}
    for (code, domain, path), values in grouped.items():
        target = catalog.file_path(domain, path, code)
        relative = target.relative_to(catalog.root).as_posix()
        if domain in {'server', 'windows'}:
            previous = target.read_text(encoding='utf-8-sig') if target.exists() else ''
            content = replace_fluent(previous, values).encode('utf-8')
        elif domain in {'web', 'android'}:
            merged = {**catalog.values(domain, path, code), **values}
            content = json_bytes(merged)
            if domain == 'web':
                content = b'export default ' + content.rstrip() + b';\n'
        else:
            content = values['document'].encode('utf-8')
        files[relative] = content

    web_metadata = {}
    web_manifest = catalog.root / 'web_client/locales/manifest.js'
    if web_manifest.exists():
        # This trusted manifest is generated as JSON-compatible JavaScript.
        # The parser below handles its property identifiers without evaluating it.
        raw = web_manifest.read_text(encoding='utf-8').split('export const LOCALE_METADATA = ', 1)[1].strip().rstrip(';')
        raw = re.sub(r'(?m)^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)', r'\1"\2"\3', raw)
        # Metadata contains nested objects, unlike literal text catalogs.
        raw = re.sub(r',\s*([}\]])', r'\1', raw)
        web_metadata = json.loads(raw)
    mobile_path = catalog.root / 'mobile_client/locales/metadata.json'
    mobile_metadata = json.loads(mobile_path.read_text(encoding='utf-8')) if mobile_path.exists() else {'defaultLocale': 'en', 'locales': {}}
    for code, metadata in data['languages'].items():
        code = language_code(code)
        base = catalog.languages().get(code, {})
        contributors = list(dict.fromkeys([*base.get('translators', []), *metadata['contributors']]))
        native = metadata['native_name']
        name = metadata['name']
        direction = Locale.parse(code, sep='-').character_order
        direction = 'rtl' if direction == 'right-to-left' else 'ltr'
        files[f'server/locales/{code}/metadata.json'] = json_bytes({
            'code': code, 'name': name, 'native_name': native, 'translators': contributors,
            'official': base.get('official', False),
            'fallback_units': sorted((set(base.get('fallback_units', [])) |
                                      {item['unit_id'] for item in dependencies if item['language'] == code}) -
                                     {item['unit_id'] for item in data['entries'] if item['language'] == code}),
        })
        files.setdefault(f'server/locales/{code}/translation_fallback.ftl', b'# Untranslated entries use the default language.\n')
        for domain, path in (('windows', 'client.ftl'), ('web', 'catalog.js'), ('android', 'client.json')):
            relative = catalog.file_path(domain, path, code).relative_to(catalog.root).as_posix()
            if relative not in files and not (catalog.root / relative).exists():
                files[relative] = b'export default {};\n' if domain == 'web' else b'{}\n' if domain == 'android' else b'# Untranslated entries use the default language.\n'
        web_metadata[code] = {**web_metadata.get(code, {}), 'name': name, 'nativeName': native,
                              'direction': direction, 'contributors': contributors,
                              'official': web_metadata.get(code, {}).get('official', False)}
        mobile_metadata['locales'][code] = {**mobile_metadata['locales'].get(code, {}),
                                          'name': name, 'nativeName': native, 'direction': direction,
                                          'contributors': contributors,
                                          'official': mobile_metadata['locales'].get(code, {}).get('official', False)}
    if data['languages']:
        files['web_client/locales/manifest.js'] = b'export const DEFAULT_LOCALE = "en";\n\nexport const LOCALE_METADATA = ' + json_bytes(web_metadata).rstrip() + b';\n'
        files['mobile_client/locales/metadata.json'] = json_bytes(mobile_metadata)
        files['mobile_client/src/i18n/localeCatalogs.ts'] = mobile_registry(mobile_metadata, catalog)
    return files


def mobile_registry(metadata, catalog):
    imports, info, entries = [], [], []
    codes = {p.parent.name for p in (catalog.root / 'mobile_client/locales').glob('*/client.json')} | set(metadata['locales'])
    for code in sorted(codes):
        language_code(code)
        binding = 'catalog_' + code.replace('-', '_')
        imports.append(f'import {binding} from "../../locales/{code}/client.json";')
        item = metadata['locales'].get(code, {})
        item = {'name': item.get('name', code), 'nativeName': item.get('nativeName', item.get('name', code)),
                'direction': item.get('direction', 'ltr'), 'contributors': item.get('contributors', []),
                'official': item.get('official', False)}
        info.append('  ' + json.dumps(code) + ': ' + json.dumps(item, ensure_ascii=False) + ',')
        entries.append('  ' + json.dumps(code) + ': ' + binding + ',')
    return ('\n'.join(imports) + '\n\nexport const DEFAULT_LOCALE = ' + json.dumps(metadata['defaultLocale']) + ';\n\n'
            + 'export const LOCALE_METADATA = {\n' + '\n'.join(info) + '\n} as const;\n\n'
            + 'export const localeCatalogs = {\n' + '\n'.join(entries) + '\n} as const;\n\n'
            + 'export type MobileLocale = keyof typeof localeCatalogs;\n').encode('utf-8')


def export_bundle(data, catalog, output):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    files = build_files(data, catalog)
    manifest = {'format': 1, 'entries': data['entries'], 'languages': data['languages'],
                'fallback_dependencies': grouped_values(data, catalog)[1],
                'files': {name: {'bytes': len(content), 'sha256': fingerprint(content.decode('utf-8'))}
                          for name, content in files.items()}}
    files['translation-manifest.json'] = json_bytes(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.translation-', suffix='.partial', dir=output.parent)
    try:
        with os.fdopen(descriptor, 'w+b') as stream:
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, content in sorted(files.items()):
                    archive.writestr(name, content)
            stream.flush()
            os.fsync(stream.fileno())
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError('Corrupt translation export')
        # A same-filesystem hard link publishes the complete verified file
        # atomically and refuses to overwrite a concurrently created output.
        os.link(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return output
