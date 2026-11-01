import json

import pytest

from server.core.release_artifacts import load_release_registry


def load(tmp_path, **changes):
    manifest = {"version": "1.0", "sounds_version": "13", "targets": {}}
    manifest.update(changes)
    path = tmp_path / "releases.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return load_release_registry(path, version="1.0", sounds_version="13")


def test_unpublished_clients_never_fall_back_to_upstream_latest(tmp_path):
    registry = load(tmp_path)
    for artifacts in registry.values():
        assert not artifacts.application.available
        assert not artifacts.sounds.available


def test_operator_can_pin_windows_and_android_independently(tmp_path):
    registry = load(tmp_path, targets={
        "windows": {"application": {
            "url": "https://play.example/releases/1/PlayAural.zip",
            "delivery": "windows_zip", "sha256": "a" * 64}},
        "android": {"application": {
            "url": "https://play.example/releases/1/PlayAural.apk",
            "delivery": "browser"}},
    })
    assert registry["windows"].application.sha256 == "a" * 64
    assert registry["android"].application.available
    assert not registry["android"].sounds.available
    assert not registry["linux"].application.available


def test_native_build_identity_is_immutable_and_optional_for_legacy_registries(tmp_path):
    registry = load(tmp_path, targets={'android': {'application': {
        'url': 'https://play.example/releases/approved/PlayAural.apk', 'delivery': 'browser', 'build_id': 'a' * 40}}})
    assert registry['android'].packet('application', '1.0')['build_id'] == 'a' * 40
    with pytest.raises(ValueError):
        load(tmp_path, targets={'android': {'application': {
            'url': 'https://play.example/PlayAural.apk', 'delivery': 'browser', 'build_id': '../latest'}}})


@pytest.mark.parametrize("changes", [
    {"version": "2.0"}, {"sounds_version": "14"},
    {"targets": {"unknown": {}}}, {"targets": []},
    {"targets": {"windows": {"unexpected": {}}}},
    {"targets": {"windows": {"application": {"url": 42}}}},
    {"targets": {"android": {"application": {
        "url": "https://example.com/releases/latest/PlayAural.apk", "delivery": "browser"}}}},
    {"targets": {"android": {"application": {
        "url": "https://example.com/PlayAural.zip", "delivery": "windows_zip"}}}},
])
def test_rejects_stale_unsafe_or_wrong_platform_manifests(tmp_path, changes):
    with pytest.raises(ValueError):
        load(tmp_path, **changes)
