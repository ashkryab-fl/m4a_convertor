# Invoked by start.bat. Saved as UTF-8 with BOM for Windows PowerShell 5.1.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
# Probe installed runtimes without letting the Windows Python manager install globally.
$env:PYTHON_MANAGER_AUTOMATIC_INSTALL = '0'
Remove-Item Env:\PYLAUNCHER_ALLOW_INSTALL -ErrorAction SilentlyContinue
$launchArguments = @($args)

function Test-ConverterPython {
    param([string]$Executable, [string[]]$PrefixArguments = @())
    try {
        & $Executable @PrefixArguments -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

try {
    $pythonExe = $null
    $pythonArguments = @()
    if ($env:M4A_FORCE_BUNDLED_PYTHON -ne '1') {
        $localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
        if ((Test-Path -LiteralPath $localPython) -and (Test-ConverterPython $localPython)) {
            $pythonExe = $localPython
        }
        if (-not $pythonExe) {
            $launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue
            if ($launcher -and (Test-ConverterPython $launcher.Source @('-3'))) {
                $pythonExe = $launcher.Source
                $pythonArguments = @('-3')
            }
        }
        if (-not $pythonExe) {
            foreach ($name in @('python', 'python3')) {
                $candidate = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue
                # Skip Microsoft Store execution aliases; they are not installed Python runtimes.
                if ($candidate -and $candidate.Source -notlike '*\WindowsApps\*' -and
                    (Test-ConverterPython $candidate.Source)) {
                    $pythonExe = $candidate.Source
                    break
                }
            }
        }
    }

    if (-not $pythonExe) {
        $runtimeDir = Join-Path $PSScriptRoot '.runtime'
        $uvExe = Join-Path $runtimeDir 'bin\uv.exe'
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $runtimeDir 'python'
        $env:UV_CACHE_DIR = Join-Path $runtimeDir 'cache'
        if (-not (Test-Path -LiteralPath $uvExe)) {
            Write-Host 'Python не найден. Загрузка локального установщика (нужен интернет)…'
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $env:UV_UNMANAGED_INSTALL = Join-Path $runtimeDir 'bin'
            $installer = Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1'
            & ([scriptblock]::Create($installer))
            if (-not (Test-Path -LiteralPath $uvExe)) { throw 'Установка uv не завершена.' }
        }
        Write-Host 'Подготовка локального Python…'
        & $uvExe python install --no-bin --no-registry --no-config 3.12
        if ($LASTEXITCODE -ne 0) { throw 'Не удалось загрузить Python. Проверьте подключение к интернету.' }
        $pythonExe = (& $uvExe python find --system --managed-python --no-config 3.12)
        if ($LASTEXITCODE -ne 0 -or -not $pythonExe) { throw 'Не удалось найти загруженный Python.' }
        $pythonExe = $pythonExe.Trim()
    }
    & $pythonExe @pythonArguments (Join-Path $PSScriptRoot 'launch.py') @launchArguments
    exit $LASTEXITCODE
} catch {
    Write-Host "Не удалось запустить конвертер: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
