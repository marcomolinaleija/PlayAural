"""Finalize a PyInstaller build and retain the licenses of installed packages."""
import argparse
import importlib.metadata
import shutil
import subprocess
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("dist", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
release = args.dist / "PlayAural"
contents = release / "_internal"
shutil.copy2(args.dist / "updater.exe", release / "updater.exe")
shutil.copytree(root / "client/locales", contents / "locales", dirs_exist_ok=True)
for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
    shutil.copy2(root / name, release / name)
with zipfile.ZipFile(next((root / "client/vendor").glob("cosmos-*.whl"))) as wheel:
    license_name = next(name for name in wheel.namelist() if name.endswith(".dist-info/licenses/LICENSE"))
    (contents / "cosmos/LICENSE").write_bytes(wheel.read(license_name))
    for name in ("cosmos.pyd", "phonon.dll"):
        assert (contents / "cosmos" / name).read_bytes() == wheel.read("cosmos/" + name)
for required in (
    "accessible_output2/lib/nvdaControllerClient64.dll",
    "_sounddevice_data/portaudio-binaries/libportaudio64bit.dll",
    "livekit/rtc/resources/livekit_ffi.dll",
    "livekit/rtc/resources/LICENSE.md",
    "cosmos/third_party/steam_audio/THIRDPARTY.md",
    "cosmos/third_party/steam_audio/UPSTREAM.json",
):
    assert (contents / required).is_file(), required
for distribution in importlib.metadata.distributions():
    for entry in distribution.files or ():
        if ".." in entry.parts:
            continue
        if not any(token in entry.name.lower() for token in ("license", "notice", "copying")):
            continue
        source = Path(distribution.locate_file(entry))
        if source.is_file():
            target = release / "dependency-licenses" / distribution.metadata["Name"] / entry
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
(release / "SOURCE.txt").write_text(
    f"PlayAural Marco, based on Daoductrung/PlayAural.\n"
    f"Corresponding source: https://github.com/marcomolinaleija/PlayAural/tree/{commit}\n"
    "Server: wss://play.marco-ml.com\n", encoding="utf-8")
print("Desktop files, runtime libraries and dependency notices verified")
