param([Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolRoot = 'D:\Software\Microsoft Visual Studio\Community\VC\Tools\MSVC\14.44.35207'
$sdkRoot = 'D:\Windows Kits\10'
$sdkVersion = '10.0.26100.0'
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
    Get-FileHash -LiteralPath '.\XInput1_3.dll' -Algorithm SHA256
} finally { Pop-Location }
