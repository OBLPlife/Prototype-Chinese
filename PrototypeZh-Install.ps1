param([string]$Game = 'D:\Software\Steam\steamapps\common\Prototype', [switch]$AcceptRisk)
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$package = Join-Path $workspace 'work\PrototypeZh\build-0.2.13-font-weights\package'
$options = @()
if ($AcceptRisk) { $options += '--accept-risk' }
& python (Join-Path $PSScriptRoot 'packaging\release_install.py') install --game $Game --package $package @options
if ($LASTEXITCODE -eq 2) { return }
if ($LASTEXITCODE -ne 0) { throw 'PrototypeZh installation failed. See the specific error above.' }
