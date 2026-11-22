param([string]$Game = 'D:\Software\Steam\steamapps\common\Prototype')
$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'tools\setup.py') status --game $Game
if ($LASTEXITCODE -ne 0) { throw 'PrototypeZh verification failed. See the specific error above.' }
