param(
    [ValidateSet("server", "local", "none")]
    [string]$Render = "server",

    [ValidateSet("svg", "png")]
    [string]$Format = "svg",

    [string]$CondaEnv = "base",

    [string]$Server = "https://www.plantuml.com",

    [string]$PlantumlJar = "",

    [string]$CondaBat = "D:\miniconda3\condabin\conda.bat",

    [string]$CodexCommand = "",

    [string]$RenderOnlyRun = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")
$generator = Join-Path $scriptDir "generate_sysml.py"

function Add-PathPrefix {
    param([string]$PathToAdd)
    if ($PathToAdd.Trim().Length -eq 0) {
        return
    }
    if (Test-Path -LiteralPath $PathToAdd) {
        $env:Path = "$PathToAdd;$env:Path"
    }
}

function Add-CodexStandaloneRuntimePath {
    $standaloneRoot = Join-Path $env:USERPROFILE ".codex\packages\standalone\releases"
    if (-not (Test-Path -LiteralPath $standaloneRoot)) {
        return
    }

    $packages = Get-ChildItem -LiteralPath $standaloneRoot -Directory -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending

    foreach ($package in $packages) {
        $manifestPath = Join-Path $package.FullName "codex-package.json"
        if (-not (Test-Path -LiteralPath $manifestPath)) {
            continue
        }

        try {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        } catch {
            continue
        }

        $resourcesDir = Join-Path $package.FullName $manifest.resourcesDir
        $pathDir = Join-Path $package.FullName $manifest.pathDir
        Add-PathPrefix $resourcesDir
        Add-PathPrefix $pathDir
        return
    }
}

if (-not (Test-Path -LiteralPath $CondaBat)) {
    throw "Cannot find conda.bat at '$CondaBat'. Pass -CondaBat with the full path to your conda.bat."
}

if (-not (Test-Path -LiteralPath $generator)) {
    throw "Cannot find generator script: $generator"
}

Add-CodexStandaloneRuntimePath
$env:CODEX_HOST_PATH = $env:Path

if ($CodexCommand.Trim().Length -eq 0 -and $RenderOnlyRun.Trim().Length -eq 0) {
    $installedCodex = Join-Path $env:LOCALAPPDATA "Programs\OpenAI\Codex\bin\codex.exe"
    if (Test-Path -LiteralPath $installedCodex) {
        $CodexCommand = $installedCodex
    } else {
        $codexFromHost = Get-Command codex -ErrorAction SilentlyContinue
        if ($null -ne $codexFromHost) {
        if ($codexFromHost.Source -like "*\WindowsApps\*") {
            $wrapper = Join-Path $env:TEMP "sysml-codex-wrapper.cmd"
            Set-Content -LiteralPath $wrapper -Encoding ASCII -Value "@echo off`r`ncodex %*"
            $CodexCommand = $wrapper
        } else {
            $CodexCommand = $codexFromHost.Source
        }
        } else {
        throw @"
Cannot find the Codex CLI command in this PowerShell session.

The Codex desktop app and the terminal `codex` command are separate entry points. This automation needs the terminal CLI because it calls `codex exec`.

Please verify one of these in the same PowerShell window:

  codex --version

If that command works, rerun this script. If it does not work, install or expose the Codex CLI, or pass a real executable/wrapper with:

  -CodexCommand <path-or-command>
"@
        }
    }
}

$argsList = @(
    "run",
    "-n",
    $CondaEnv,
    "python",
    $generator,
    "--repo",
    $repoRoot,
    "--render",
    $Render,
    "--format",
    $Format,
    "--server",
    $Server
)

if ($CodexCommand.Trim().Length -gt 0) {
    $argsList += @("--codex-command", $CodexCommand)
}

if ($PlantumlJar.Trim().Length -gt 0) {
    $argsList += @("--plantuml-jar", $PlantumlJar)
}

if ($RenderOnlyRun.Trim().Length -gt 0) {
    $argsList += @("--render-only-run", $RenderOnlyRun)
}

Write-Host "+ $CondaBat $($argsList -join ' ')"
& $CondaBat @argsList
exit $LASTEXITCODE
