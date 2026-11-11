<#
.SYNOPSIS
    Compila el cliente de escritorio de PlayAural para distribución a testers y genera un ZIP listo para compartir.
.DESCRIPTION
    Script local para testers que:
    1. Detecta y verifica el entorno Python con todas las dependencias necesarias.
    2. Registra el commit Git en client/release-build.json.
    3. Limpia artefactos previos de compilación.
    4. Compila updater.exe y PlayAural.exe usando PyInstaller.
    5. Ensambla y valida librerías nativas, sonidos, traducciones y licencias.
    6. Genera un archivo ZIP (dist\PlayAural-tester.zip) con la carpeta PlayAural lista para compartir.
.PARAMETER ZipName
    Nombre del archivo ZIP de salida en la carpeta dist (por defecto: PlayAural-tester.zip).
.PARAMETER SkipClean
    Omite la limpieza previa de dist\ y build\.
#>
[CmdletBinding()]
param(
    [string]$ZipName = "PlayAural-tester.zip",
    [switch]$SkipClean,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path $PSScriptRoot).Path
Push-Location $root

try {
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  PlayAural - Compilacion de Cliente para Testers" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""

    # 1. Detectar interprete de Python
    Write-Host "[1/6] Buscando entorno de Python..." -ForegroundColor Yellow
    $candidates = @(
        (Join-Path $root "client\.venv\Scripts\python.exe"),
        (Join-Path $root ".venv\Scripts\python.exe"),
        (Join-Path $root "venv\Scripts\python.exe")
    )
    if ($env:VIRTUAL_ENV) {
        $candidates = @((Join-Path $env:VIRTUAL_ENV "Scripts\python.exe")) + $candidates
    }

    $python = $null
    foreach ($cand in $candidates) {
        if (Test-Path $cand) {
            $python = $cand
            break
        }
    }

    if (-not $python) {
        $sysPython = Get-Command python -ErrorAction SilentlyContinue
        if ($sysPython) {
            $python = $sysPython.Source
        }
    }

    if (-not $python) {
        throw "No se encontro ningun interprete de Python en client\.venv ni en el PATH."
    }

    Write-Host "      Interprete seleccionado: $python"

    # Verificar dependencias minimas de build
    $depsCheck = "import sys, PyInstaller, wx, accessible_output2, cosmos, keyring, requests, psutil, websockets, fluent.runtime, numpy, sounddevice; from livekit import rtc; print('OK')"
    $checkResult = & $python -c $depsCheck 2>$null
    if ($LASTEXITCODE -ne 0 -or $checkResult -notmatch "OK") {
        Write-Host "      Faltan dependencias en el entorno. Intentando resolver con uv..." -ForegroundColor Yellow
        $uv = Get-Command uv -ErrorAction SilentlyContinue
        if ($uv) {
            & uv sync --project client --extra dev
            if ($LASTEXITCODE -ne 0) { throw "Fallo uv sync para el cliente." }
            $python = Join-Path $root "client\.venv\Scripts\python.exe"
            & uv pip install --python $python "pyinstaller>=6.0"
            if ($LASTEXITCODE -ne 0) { throw "Fallo la instalacion de PyInstaller con uv." }
        } else {
            throw "El entorno Python no cuenta con las dependencias requeridas (wx, cosmos, livekit, pyinstaller, etc.) y no se encontro 'uv'."
        }
    }
    Write-Host "      Dependencias verificadas correctamente." -ForegroundColor Green
    Write-Host ""

    # 2. Registrar commit en release-build.json
    Write-Host "[2/6] Registrando commit de Git..." -ForegroundColor Yellow
    $gitCommit = try { (& git rev-parse HEAD 2>$null).Trim() } catch { $null }
    if ($gitCommit) {
        $identityFile = Join-Path $root "client\release-build.json"
        $identityJson = @{ source_commit = $gitCommit } | ConvertTo-Json
        [IO.File]::WriteAllText($identityFile, $identityJson, [System.Text.UTF8Encoding]::new($false))
        Write-Host "      Commit: $gitCommit"
    } else {
        Write-Host "      No se detecto repositorio Git, continuando con metadata existente." -ForegroundColor DarkGray
    }
    Write-Host ""

    # 3. Limpieza de artefactos previos
    if (-not $SkipClean) {
        Write-Host "[3/6] Limpiando carpetas de salida anteriores..." -ForegroundColor Yellow
        $buildDir = Join-Path $root "build"
        $distPlayAural = Join-Path $root "dist\PlayAural"
        $distUpdater = Join-Path $root "dist\updater.exe"
        $zipTarget = Join-Path $root "dist\$ZipName"

        if (Test-Path $buildDir) { Remove-Item -Recurse -Force $buildDir }
        if (Test-Path $distPlayAural) { Remove-Item -Recurse -Force $distPlayAural }
        if (Test-Path $distUpdater) { Remove-Item -Force $distUpdater }
        if (Test-Path $zipTarget) { Remove-Item -Force $zipTarget }
        Write-Host "      Salidas anteriores limpiadas." -ForegroundColor Green
        Write-Host ""
    } else {
        Write-Host "[3/6] Omitiendo limpieza (--SkipClean)." -ForegroundColor DarkGray
        Write-Host ""
    }

    # 4. Compilacion con PyInstaller
    Write-Host "[4/6] Compilando cliente y utilitarios con PyInstaller..." -ForegroundColor Yellow
    $distDir = Join-Path $root "dist"

    Write-Host "      -> Compilando updater.exe..." -ForegroundColor Cyan
    & $python -m PyInstaller --clean --noconfirm --distpath $distDir (Join-Path $root "updater.spec")
    if ($LASTEXITCODE -ne 0) { throw "Error al compilar updater.spec" }

    Write-Host "      -> Compilando PlayAural.exe..." -ForegroundColor Cyan
    & $python -m PyInstaller --clean --noconfirm --distpath $distDir (Join-Path $root "PlayAural.spec")
    if ($LASTEXITCODE -ne 0) { throw "Error al compilar PlayAural.spec" }

    Write-Host "      Compilacion de ejecutables completada." -ForegroundColor Green
    Write-Host ""

    # 5. Ensamblaje, verificación y empaquetado en ZIP
    Write-Host "[5/6] Finalizando carpeta y generando ZIP para testers..." -ForegroundColor Yellow

    $packageScript = @'
import hashlib
import json
import pathlib
import shutil
import sys
import zipfile

root = pathlib.Path.cwd()
dist_root = root / "dist" / "PlayAural"
contents_dir = dist_root / "_internal" if (dist_root / "_internal").is_dir() else dist_root
zip_name = sys.argv[1] if len(sys.argv) > 1 else "PlayAural-tester.zip"
zip_path = root / "dist" / zip_name

if not dist_root.is_dir():
    sys.exit(f"Directorio no encontrado: {dist_root}")

# 1. Copiar updater.exe a la raiz de distribucion
updater_exe = root / "dist" / "updater.exe"
if updater_exe.is_file():
    shutil.copy2(updater_exe, dist_root / "updater.exe")
else:
    sys.exit("updater.exe no fue generado en dist/")

# 2. Copiar licencias y avisos
for lic in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
    src = root / lic
    if src.is_file():
        shutil.copy2(src, dist_root / lic)

# 3. Sincronizar locales
locales_src = root / "client" / "locales"
locales_dst = contents_dir / "locales"
if locales_src.is_dir():
    shutil.copytree(locales_src, locales_dst, dirs_exist_ok=True)

# 4. Asegurar bytes exactos de licencia Cosmos desde wheel
wheels = list((root / "client" / "vendor").glob("cosmos-*.whl"))
if wheels:
    with zipfile.ZipFile(wheels[0]) as wheel:
        lic_entry = next((n for n in wheel.namelist() if n.endswith(".dist-info/licenses/LICENSE")), None)
        if lic_entry:
            (contents_dir / "cosmos" / "LICENSE").write_bytes(wheel.read(lic_entry))

# 5. Verificacion de integridad
required = [
    dist_root / "PlayAural.exe",
    dist_root / "updater.exe",
    contents_dir / "sounds",
    contents_dir / "locales",
    contents_dir / "accessible_output2" / "lib" / "nvdaControllerClient64.dll",
    contents_dir / "_sounddevice_data" / "portaudio-binaries" / "libportaudio64bit.dll",
    contents_dir / "livekit" / "rtc" / "resources" / "livekit_ffi.dll",
    contents_dir / "livekit" / "rtc" / "resources" / "LICENSE.md",
    contents_dir / "cosmos" / "cosmos.pyd",
    contents_dir / "cosmos" / "phonon.dll",
    contents_dir / "cosmos" / "LICENSE",
    contents_dir / "cosmos" / "third_party" / "steam_audio" / "LICENSE.md",
    contents_dir / "cosmos" / "third_party" / "steam_audio" / "THIRDPARTY.md",
    contents_dir / "cosmos" / "third_party" / "steam_audio" / "TRADEMARK_RIGHTS.md",
    contents_dir / "cosmos" / "third_party" / "steam_audio" / "UPSTREAM.json",
]
for item in required:
    if not item.exists():
        sys.exit(f"Archivo o carpeta requerida faltante: {item}")

print("      Verificaciones de integridad aprobadas.")

# 6. Crear archivo ZIP empaquetando todo bajo la carpeta 'PlayAural'
if zip_path.is_file():
    zip_path.unlink()

print(f"      Empaquetando en {zip_path.name}...")
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
    for path in sorted(dist_root.rglob("*")):
        if path.is_file():
            arcname = "PlayAural/" + path.relative_to(dist_root).as_posix()
            archive.write(path, arcname)

with zipfile.ZipFile(zip_path, "r") as test_archive:
    if test_archive.testzip() is not None:
        sys.exit("Error: La integridad del archivo ZIP generado esta corrupta.")

size_mb = zip_path.stat().st_size / (1024 * 1024)
sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
print(f"ZIP_READY|{zip_path}|{size_mb:.2f}|{sha}")
'@

    $packOutput = $packageScript | & $python - $ZipName
    if ($LASTEXITCODE -ne 0) {
        throw "Error al empaquetar o verificar el release para testers."
    }

    $zipInfo = $packOutput | Where-Object { $_ -match "^ZIP_READY\|" }
    $parts = $zipInfo -split "\|"
    $finalZipPath = $parts[1]
    $finalSizeMb = $parts[2]
    $finalSha = $parts[3]

    Write-Host ""
    Write-Host "[6/6] Compilacion completada con exito." -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  RESUMEN DE SALIDA" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  Carpeta de ejecutable: dist\PlayAural\" -ForegroundColor White
    Write-Host "  Archivo ZIP listo:     $finalZipPath" -ForegroundColor Green
    Write-Host "  Tamano:                $finalSizeMb MB" -ForegroundColor White
    Write-Host "  SHA-256:               $finalSha" -ForegroundColor Gray
    Write-Host "============================================================" -ForegroundColor Cyan

} finally {
    Pop-Location
}
