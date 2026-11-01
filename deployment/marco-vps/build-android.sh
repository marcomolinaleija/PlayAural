#!/usr/bin/env bash
set -euo pipefail
export PLAYAURAL_MARCO_BUILD=1
export EXPO_PUBLIC_PLAYAURAL_SERVER_URL=wss://play.marco-ml.com
export PLAYAURAL_ANDROID_VERSION_CODE=${PLAYAURAL_ANDROID_VERSION_CODE:-10503001}
cd /workspace/mobile_client
node --version
java -version
npm ci
npm run typecheck
npx expo prebuild --platform android --no-install
mkdir -p android/app/src/main/assets
cp /workspace/LICENSE android/app/src/main/assets/PlayAural-LICENSE.txt
cp /workspace/THIRD_PARTY_NOTICES.md android/app/src/main/assets/PlayAural-NOTICES.txt
printf 'Corresponding source: https://github.com/marcomolinaleija/PlayAural/tree/%s\n' "$(git -C /workspace rev-parse HEAD)" > android/app/src/main/assets/PlayAural-SOURCE.txt
python3 - <<'PY'
from pathlib import Path
p = Path('android/gradle/wrapper/gradle-wrapper.properties')
p.write_text(p.read_text().replace('gradle-9.0.0-bin.zip', 'gradle-8.14.3-bin.zip'))
PY
cd android
chmod +x gradlew
./gradlew assembleRelease --no-daemon --max-workers=2
test -f app/build/outputs/apk/release/app-release.apk
echo 'APK built; sign with the private deployment key before publication.'
