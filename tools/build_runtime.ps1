param(
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$VcTools = $env:VCToolsInstallDir,
    [string]$WindowsSdk = $env:WindowsSdkDir,
    [string]$SdkVersion = $env:WindowsSDKVersion
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $VcTools) {
    $locator = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $locator)) { throw 'Specify the installed MSVC directory with -VcTools.' }
    $installation = & $locator -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $installation) { throw 'MSVC x86 tools are required to compile the runtime.' }
    $versions = Join-Path $installation 'VC\Tools\MSVC'
    $VcTools = Join-Path $versions '14.44.35207'
    if (-not (Test-Path -LiteralPath $VcTools)) {
        $defaultVersion = (Get-Content -LiteralPath (Join-Path $installation 'VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt') -Raw).Trim()
        $VcTools = Join-Path $versions $defaultVersion
    }
}
if (-not $WindowsSdk) {
    $WindowsSdk = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots' -Name KitsRoot10).KitsRoot10
}
if (-not $SdkVersion) {
    $includeRoot = Join-Path $WindowsSdk 'Include'
    $SdkVersion = '10.0.26100.0'
    if (-not (Test-Path -LiteralPath (Join-Path $includeRoot $SdkVersion))) {
        $SdkVersion = (Get-ChildItem -LiteralPath $includeRoot -Directory |
            Where-Object Name -Match '^\d+(\.\d+){3}$' |
            Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1).Name
    }
}
if (-not $SdkVersion) { throw 'Specify an installed Windows SDK version with -SdkVersion.' }
$toolRoot = $VcTools
$sdkRoot = $WindowsSdk
$sdkVersion = $SdkVersion.TrimEnd([char[]]'\/')
$compiler = Join-Path $toolRoot 'bin\Hostx64\x86\cl.exe'
$env:INCLUDE = @((Join-Path $toolRoot 'include'),(Join-Path $sdkRoot "Include\$sdkVersion\ucrt"),(Join-Path $sdkRoot "Include\$sdkVersion\shared"),(Join-Path $sdkRoot "Include\$sdkVersion\um")) -join ';'
$env:LIB = @((Join-Path $toolRoot 'lib\x86'),(Join-Path $sdkRoot "Lib\$sdkVersion\ucrt\x86"),(Join-Path $sdkRoot "Lib\$sdkVersion\um\x86")) -join ';'
$env:PATH = (Split-Path -Parent $compiler) + ';' + $env:PATH
$outputRoot = [IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
Push-Location $outputRoot
try {
    & $compiler /nologo /LD /MT /O2 /EHsc /W4 /WX /utf-8 /std:c++17 /D_WIN32_WINNT=0x0602 `
        (Join-Path $projectRoot 'runtime\xinput_entry.cpp') /Fe:XInput1_3.dll /link `
        ("/DEF:"+(Join-Path $projectRoot 'runtime\xinput_entry.def')) /MACHINE:X86 /DYNAMICBASE /NXCOMPAT /INCREMENTAL:NO kernel32.lib
    if ($LASTEXITCODE -ne 0) { throw 'Localization memory support build failed.' }
    $dllPath = Join-Path $outputRoot 'XInput1_3.dll'
    $hashAlgorithm = [Security.Cryptography.SHA256]::Create()
    $dllStream = [IO.File]::OpenRead($dllPath)
    try {
        [pscustomobject]@{
            Algorithm = 'SHA256'
            Hash = [BitConverter]::ToString($hashAlgorithm.ComputeHash($dllStream)).Replace('-', '')
            Path = $dllPath
        }
    } finally {
        $dllStream.Dispose()
        $hashAlgorithm.Dispose()
    }
} finally { Pop-Location }
