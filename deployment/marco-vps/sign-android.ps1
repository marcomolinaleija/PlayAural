[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Apk,
    [Parameter(Mandatory)][string]$OutputApk,
    [Parameter(Mandatory)][string]$Keystore,
    [Parameter(Mandatory)][string]$SigningConfig,
    [string]$BuildTools = (Join-Path $env:LOCALAPPDATA 'Android/Sdk/build-tools/36.0.0')
)
$ErrorActionPreference = 'Stop'
$signing = Get-Content -LiteralPath $SigningConfig -Raw | ConvertFrom-Json
$env:PLAYAURAL_SIGNING_PASSWORD = $signing.password
try {
    $aligned = $OutputApk + '.aligned.apk'
    & (Join-Path $BuildTools 'zipalign.exe') -P 16 -f 4 $Apk $aligned
    if ($LASTEXITCODE) { throw 'APK alignment failed' }
    & (Join-Path $BuildTools 'apksigner.bat') sign --ks $Keystore --ks-key-alias $signing.alias `
        --ks-pass env:PLAYAURAL_SIGNING_PASSWORD --key-pass env:PLAYAURAL_SIGNING_PASSWORD `
        --out $OutputApk $aligned
    if ($LASTEXITCODE) { throw 'APK signing failed' }
    & (Join-Path $BuildTools 'apksigner.bat') verify --verbose --print-certs $OutputApk
    if ($LASTEXITCODE) { throw 'APK signature verification failed' }
    & (Join-Path $BuildTools 'zipalign.exe') -c -P 16 -v 4 $OutputApk
    if ($LASTEXITCODE) { throw 'Signed APK alignment verification failed' }
    Remove-Item -LiteralPath $aligned
} finally { Remove-Item Env:PLAYAURAL_SIGNING_PASSWORD -ErrorAction SilentlyContinue }
