# Thin PowerShell wrapper (Windows) around install.py.
# Locates a Python 3.10+ interpreter, then hands off to install.py, which holds
# all the real logic (single source of truth across platforms).
$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Py($exe) {
    try {
        & $exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

$py = $null
foreach ($candidate in @("py", "python", "python3")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        if (Test-Py $candidate) { $py = $candidate; break }
    }
}

if (-not $py) {
    Write-Error "[wat-install] No Python 3.10+ found on PATH. Install one and retry."
    exit 1
}

& $py (Join-Path $here "install.py") @args
exit $LASTEXITCODE
