param([string]$Game = 'D:\Software\Steam\steamapps\common\Prototype')
$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'packaging\release_install.py') restore --game $Game
if ($LASTEXITCODE -ne 0) { throw 'PrototypeZh uninstall failed. See the specific error above.' }
