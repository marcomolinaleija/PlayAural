<#
.SYNOPSIS
    Limpia todos los residuos generados por la compilación (dist, build, release-build.json).
.DESCRIPTION
    Elimina por completo todas las carpetas y archivos generados al compilar:
    - dist\ (incluyendo ejecutables, subcarpetas y ZIPs)
    - build\ (archivos intermedios de PyInstaller)
    - client\release-build.json (identificador temporal de build)
.PARAMETER NoPause
    Omite la pausa al final si se ejecuta desde batch.
#>
[CmdletBinding()]
param(
    [switch]$NoPause
)

$ErrorActionPreference = "SilentlyContinue"
$root = (Resolve-Path $PSScriptRoot).Path

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  PlayAural - Limpieza Total de Compilacion" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$targets = @(
    @{ Path = (Join-Path $root "dist"); Description = "Carpeta dist (ejecutables, zips y paquetes)" },
    @{ Path = (Join-Path $root "build"); Description = "Carpeta build (temporales de PyInstaller)" },
    @{ Path = (Join-Path $root "client\release-build.json"); Description = "Metadatos temporales de build" }
)

$itemsRemoved = 0

foreach ($target in $targets) {
    if (Test-Path $target.Path) {
        Write-Host "  -> Eliminando $($target.Description)..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $target.Path -ErrorAction SilentlyContinue
        $itemsRemoved++
    }
}

Write-Host ""
if ($itemsRemoved -gt 0) {
    Write-Host "[OK] Limpieza total completada. Se eliminaron $itemsRemoved carpetas/archivos de compilacion." -ForegroundColor Green
} else {
    Write-Host "[OK] Todo limpio. No habia carpetas 'dist', 'build' ni residuos de compilacion." -ForegroundColor Green
}
