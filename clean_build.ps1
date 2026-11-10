<#
.SYNOPSIS
    Limpia los artefactos generados por la compilación del cliente (carpetas build, dist, ejecutables y archivos ZIP).
.DESCRIPTION
    Elimina residuos generados por la compilación:
    - build\
    - dist\PlayAural\
    - dist\updater.exe
    - dist\*.zip (incluyendo PlayAural-tester.zip)
    - client\release-build.json
.PARAMETER All
    Si se especifica, elimina por completo la carpeta dist\.
.PARAMETER NoPause
    Omite la pausa al final si se ejecuta desde batch.
#>
[CmdletBinding()]
param(
    [switch]$All,
    [switch]$NoPause
)

$ErrorActionPreference = "SilentlyContinue"
$root = (Resolve-Path $PSScriptRoot).Path

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  PlayAural - Limpieza de Artefactos de Compilacion" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$itemsRemoved = 0

function Remove-Target {
    param([string]$Path, [string]$Description)
    if (Test-Path $Path) {
        Write-Host "  -> Eliminando $Description`: $Path" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $Path -ErrorAction SilentlyContinue
        $script:itemsRemoved++
    }
}

# 1. Carpeta build
Remove-Target -Path (Join-Path $root "build") -Description "carpeta build"

# 2. Carpeta dist\PlayAural
Remove-Target -Path (Join-Path $root "dist\PlayAural") -Description "carpeta dist\PlayAural"

# 3. dist\updater.exe
Remove-Target -Path (Join-Path $root "dist\updater.exe") -Description "dist\updater.exe"

# 4. Archivos ZIP en dist (como PlayAural-tester.zip)
Get-ChildItem -Path (Join-Path $root "dist") -Filter "*.zip" -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-Target -Path $_.FullName -Description "archivo ZIP"
}

# 5. Metadata de release temporal
Remove-Target -Path (Join-Path $root "client\release-build.json") -Description "client\release-build.json"

# 6. Si se paso -All o si dist queda vacio
if ($All) {
    Remove-Target -Path (Join-Path $root "dist") -Description "carpeta dist completa"
} else {
    $distDir = Join-Path $root "dist"
    if (Test-Path $distDir) {
        $remaining = Get-ChildItem -Path $distDir -ErrorAction SilentlyContinue
        if ($null -eq $remaining -or $remaining.Count -eq 0) {
            Remove-Target -Path $distDir -Description "carpeta dist vacia"
        }
    }
}

Write-Host ""
if ($itemsRemoved -gt 0) {
    Write-Host "[OK] Limpieza completada exitosamente ($itemsRemoved elementos eliminados)." -ForegroundColor Green
} else {
    Write-Host "[OK] No se encontraron residuos de compilacion para eliminar." -ForegroundColor Green
}
