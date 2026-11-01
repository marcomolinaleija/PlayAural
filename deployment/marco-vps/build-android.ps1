[CmdletBinding()]
param([string]$VersionCode = '10503001')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if ((Get-PSDrive -Name ([IO.Path]::GetPathRoot($root).TrimEnd('\').TrimEnd(':'))).Free -lt 15GB) {
    throw 'Android builds need at least 15 GB free. Use the VPS Linux builder when local storage is limited.'
}
Push-Location (Join-Path $root 'mobile_client')
try {
    $env:PLAYAURAL_MARCO_BUILD = '1'
    $env:EXPO_PUBLIC_PLAYAURAL_SERVER_URL = 'wss://play.marco-ml.com'
    $env:PLAYAURAL_ANDROID_VERSION_CODE = $VersionCode
    & npm.cmd ci
    if ($LASTEXITCODE) { throw 'Android dependency installation failed' }
    & npm.cmd run typecheck
    if ($LASTEXITCODE) { throw 'Android typecheck failed' }
    & npx.cmd expo prebuild --platform android --no-install
    if ($LASTEXITCODE) { throw 'Android prebuild failed' }
    # RN's pinned Foojay 0.5 plugin uses a JVM vendor removed in Gradle 9.
    $wrapper = Join-Path (Get-Location) 'android/gradle/wrapper/gradle-wrapper.properties'
    $text = [IO.File]::ReadAllText($wrapper)
    [IO.File]::WriteAllText($wrapper, $text.Replace('gradle-9.0.0-bin.zip', 'gradle-8.14.3-bin.zip'))
    if ($env:ANDROID_HOME) {
        [IO.File]::WriteAllText((Join-Path (Get-Location) 'android/local.properties'),
            'sdk.dir=' + $env:ANDROID_HOME.Replace('\', '/'))
    }
    Push-Location android
    try {
        # React Native does not track locale JSON as bundle task inputs.
        & ./gradlew.bat :app:createBundleReleaseJsAndAssets --rerun-tasks --no-daemon --max-workers=4
        if ($LASTEXITCODE) { throw 'Android locale bundle generation failed' }
        & ./gradlew.bat assembleRelease --no-daemon --max-workers=4
        if ($LASTEXITCODE) { throw 'Android build failed' }
    } finally { Pop-Location }
    Write-Output 'APK built. Sign it using the private deployment key before publishing; never distribute the debug-signed output.'
} finally { Pop-Location }
