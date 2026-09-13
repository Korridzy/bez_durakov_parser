param(
    [ValidateSet('start', 'stop')]
    [string]$Action = 'start',
    [string]$Dataset = $env:DATASET,
    [string]$DatasetDir = $env:DATASET_DIR,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskSetup = Join-Path $taskRoot 'range\.setup'

function Find-TaskExecutable([string]$Name, [string[]]$Candidates) {
    $taskCommand = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($taskCommand) { return $taskCommand.Source }
    foreach ($taskCandidate in $Candidates) {
        if (Test-Path -LiteralPath $taskCandidate -PathType Leaf) { return $taskCandidate }
    }
    throw ($Name + ' is missing. See doc/windows-launcher.md for initial setup requirements.')
}

function Test-TaskDocker {
    $ErrorActionPreference = 'SilentlyContinue'
    & $taskDocker info --format '{{.OSType}}' *> $null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-TaskMake([string]$Target, [switch]$InDataset) {
    # Pass values through the environment so paths with spaces stay single arguments.
    $env:WEBREPORT_MAKE_TARGET = $Target
    if ($InDataset) {
        & $taskBash -c 'make -C "$DATASET_DIR" "$WEBREPORT_MAKE_TARGET"'
    } else {
        & $taskBash -c 'make "$WEBREPORT_MAKE_TARGET"'
    }
    if ($LASTEXITCODE -ne 0) {
        throw ('Command failed: make ' + $Target)
    }
}

function Test-TaskDatasetTarget([string]$Target) {
    if (-not $DatasetDir) { return $false }
    $taskMakefile = Join-Path $DatasetDir 'Makefile'
    if (-not (Test-Path -LiteralPath $taskMakefile -PathType Leaf)) { return $false }
    return [bool](Select-String -LiteralPath $taskMakefile -Pattern ('^' + [regex]::Escape($Target) + '\s*:') -Quiet)
}

function Wait-TaskHttp([string]$Url) {
    $taskDeadline = (Get-Date).AddMinutes(3)
    do {
        try {
            $taskResponse = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($taskResponse.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $taskDeadline)
    throw ('Service did not become ready: ' + $Url)
}

Push-Location -LiteralPath $taskRoot
try {
    # The selected dataset is a local preference, not part of the shared launcher.
    $taskSettingsFile = Join-Path $taskRoot 'range\webreport-launcher.json'
    if (-not $Dataset -and -not $PSBoundParameters.ContainsKey('Dataset') -and (Test-Path -LiteralPath $taskSettingsFile)) {
        $taskSettings = Get-Content -LiteralPath $taskSettingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $Dataset = $taskSettings.dataset
        if (-not $DatasetDir) { $DatasetDir = $taskSettings.datasetDir }
    }
    if ($Dataset) {
        if ($Dataset -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*$') {
            throw 'Dataset names must use letters, digits, underscores, dots or hyphens.'
        }
        if (-not $DatasetDir) { $DatasetDir = Join-Path $taskRoot ('range\' + $Dataset) }
        if (-not [IO.Path]::IsPathRooted($DatasetDir)) { $DatasetDir = Join-Path $taskRoot $DatasetDir }
        $DatasetDir = [IO.Path]::GetFullPath($DatasetDir)
        if ($Action -eq 'start' -and -not (Test-Path -LiteralPath (Join-Path $DatasetDir 'config\config.local.toml') -PathType Leaf)) {
            throw ('Dataset configuration is missing in ' + $DatasetDir)
        }
        $env:DATASET = $Dataset
        $env:DATASET_DIR = $DatasetDir.Replace('\', '/')
        if (-not $env:BD_CONFIG_LOCAL_FILE) { $env:BD_CONFIG_LOCAL_FILE = $env:DATASET_DIR + '/config/config.local.toml' }
        Write-Host ('Dataset: ' + $Dataset)
    } else {
        if ($DatasetDir) { throw 'DatasetDir requires a Dataset name.' }
        $env:DATASET = $null
        $env:DATASET_DIR = $null
        Write-Host 'Dataset: project default'
    }
    $env:COMPOSE_PROGRESS = 'plain'

    $taskDocker = Find-TaskExecutable 'docker.exe' @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
    )
    $taskGit = Find-TaskExecutable 'git.exe' @(
        (Join-Path $env:ProgramFiles 'Git\cmd\git.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe')
    )
    $taskGitRoot = Split-Path (Split-Path $taskGit -Parent) -Parent
    $taskBash = Join-Path $taskGitRoot 'bin\bash.exe'
    if (-not (Test-Path -LiteralPath $taskBash -PathType Leaf)) {
        throw 'Git Bash is missing. Install Git for Windows before starting WebReport.'
    }
    $taskMake = Find-TaskExecutable 'make.exe' @((Join-Path $taskSetup 'msys-make\usr\bin\make.exe'))
    $taskPoetry = Find-TaskExecutable 'poetry.exe' @((Join-Path $taskSetup 'poetry\Scripts\poetry.exe'))
    $taskTools = @(
        (Split-Path $taskMake -Parent),
        (Split-Path $taskPoetry -Parent),
        (Split-Path $taskDocker -Parent),
        (Join-Path $taskGitRoot 'usr\bin')
    )
    $env:PATH = ($taskTools -join ';') + ';' + $env:PATH

    if (-not (Test-TaskDocker)) {
        if ($Action -eq 'stop') {
            Write-Host 'Docker is not running. Nothing to stop.'
            exit 0
        }
        Write-Host 'Starting Docker Desktop...'
        $taskDockerRoot = Split-Path (Split-Path (Split-Path $taskDocker -Parent) -Parent) -Parent
        $taskDockerDesktop = Join-Path $taskDockerRoot 'Docker Desktop.exe'
        if (-not (Test-Path -LiteralPath $taskDockerDesktop -PathType Leaf)) {
            throw 'Start Docker Desktop with Linux containers, then run this launcher again.'
        }
        Start-Process -FilePath $taskDockerDesktop -WindowStyle Hidden
        $taskDeadline = (Get-Date).AddMinutes(3)
        while (-not (Test-TaskDocker)) {
            if ((Get-Date) -ge $taskDeadline) { throw 'Docker Desktop did not become ready.' }
            Start-Sleep -Seconds 2
        }
    }
    if ($Action -eq 'stop') {
        Invoke-TaskMake 'webreport-stop'
        if (Test-TaskDatasetTarget 'db-down') { Invoke-TaskMake 'db-down' -InDataset }
        Write-Host 'WebReport stopped. Database and chat history are preserved.'
        exit 0
    }

    if (Test-TaskDatasetTarget 'db-up') { Invoke-TaskMake 'db-up' -InDataset }
    Invoke-TaskMake 'webreport-start'
    $taskPorts = @{}
    foreach ($taskLine in Get-Content -LiteralPath 'webreport\.env') {
        if ($taskLine -match '^(WEBREPORT_(?:BACKEND|FRONTEND)_PORT)=(\d+)$') {
            $taskPorts[$Matches[1]] = [int]$Matches[2]
        }
    }
    if ($taskPorts.Count -ne 2) { throw 'Generated application ports are missing.' }
    $taskUrl = 'http://localhost:' + $taskPorts['WEBREPORT_FRONTEND_PORT']
    Wait-TaskHttp ($taskUrl + '/api/workspace')
    Wait-TaskHttp ($taskUrl + '/health')
    Write-Host ('Ready: ' + $taskUrl)
    if (-not $NoBrowser) { Start-Process -FilePath $taskUrl }
} catch {
    Write-Host ('Startup/stop failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
