import ast
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def python_constants(path):
    return {target.id: node.value.value for node in ast.parse(path.read_text()).body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            for target in node.targets if isinstance(target, ast.Name)}


def string_assignment(path, name):
    match = re.search(r'\b' + re.escape(name) + r'\s*=\s*("[^"\n]*")', path.read_text(encoding='utf-8'))
    assert match, f'Missing version constant: {name}'
    return json.loads(match.group(1))


def test_all_distributed_clients_and_sound_packs_match_server_protocol():
    server = python_constants(ROOT / 'server/core/server.py')
    expected = server['VERSION']
    assert python_constants(ROOT / 'client/version.py')['VERSION'] == expected
    assert json.loads((ROOT / 'mobile_client/package.json').read_text())['version'] == expected
    assert json.loads((ROOT / 'mobile_client/app.json').read_text())['expo']['version'] == expected
    assert string_assignment(ROOT / 'mobile_client/src/app/PlayAuralApp.tsx', 'MOBILE_CLIENT_VERSION') == expected
    assert string_assignment(ROOT / 'web_client/game.js', 'PLAYAURAL_WEB_VERSION') == expected
    for client in ('client', 'mobile_client', 'web_client'):
        assert (ROOT / client / 'sounds/version.txt').read_text().strip() == server['SOUNDS_VERSION']
