"""Package coordinated client downloads and the operator release manifest."""
import argparse
import ast
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("destination", type=Path)
parser.add_argument("--desktop", required=True, type=Path)
parser.add_argument("--android", required=True, type=Path)
parser.add_argument("--android-version-code", required=True, type=int)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
constants = {}
for node in ast.parse((root / "server/core/server.py").read_text(encoding="utf-8")).body:
    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
        constants.update({target.id: node.value.value for target in node.targets if isinstance(target, ast.Name)})
version, sounds_version = constants["VERSION"], constants["SOUNDS_VERSION"]
assert (args.desktop / "PlayAural.exe").is_file()
assert (args.desktop / "updater.exe").is_file()
assert args.android.is_file()
assert json.loads((args.desktop / '_internal/release-build.json').read_text())['source_commit'] == commit
with zipfile.ZipFile(args.android) as apk:
    assert commit.encode() in apk.read('assets/PlayAural-SOURCE.txt')
    assert commit.encode() in apk.read('assets/index.android.bundle')
sounds = args.desktop / "_internal/sounds"
assert (sounds / "version.txt").read_text().strip() == sounds_version
args.destination.mkdir(parents=True, exist_ok=False)
with zipfile.ZipFile(args.destination / "PlayAural.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
    for path in sorted(args.desktop.rglob("*")):
        if path.is_file():
            archive.write(path, "PlayAural/" + path.relative_to(args.desktop).as_posix())
with zipfile.ZipFile(args.destination / "sounds.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
    for path in sorted(sounds.rglob("*")):
        if path.is_file():
            archive.write(path, "sounds/" + path.relative_to(sounds).as_posix())
shutil.copy2(args.android, args.destination / "PlayAural.apk")
hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
          for path in args.destination.iterdir() if path.is_file()}
base = f"https://play.marco-ml.com/downloads/{commit}"
manifest = {
    "source_commit": commit, "version": version, "sounds_version": sounds_version,
    "android_version_code": args.android_version_code,
    "sha256": hashes,
    "targets": {
        "windows": {
            "application": {"url": base + "/PlayAural.zip", "delivery": "windows_zip", "sha256": hashes["PlayAural.zip"], "build_id": commit},
            "sounds": {"url": base + "/sounds.zip", "delivery": "windows_zip", "sha256": hashes["sounds.zip"]}},
        "android": {
            "application": {"url": base + "/PlayAural.apk", "delivery": "browser", "build_id": commit},
            "sounds": {"url": base + "/PlayAural.apk", "delivery": "browser"}},
    },
}
(args.destination / "release.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
(args.destination / "SHA256SUMS.txt").write_text("".join(f"{digest}  {name}\n" for name, digest in hashes.items()))
print(json.dumps({"commit": commit, "version": version, "sounds_version": sounds_version, "files": hashes}))
