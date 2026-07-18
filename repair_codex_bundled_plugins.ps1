param(
    [Parameter(Mandatory = $true)]
    [int]$MainPid
)

$ErrorActionPreference = "Continue"
$logDir = Join-Path $PSScriptRoot "logs"
$logPath = Join-Path $logDir "codex_plugin_repair_20260715.log"
$cli = "C:\Users\Lenovo\.codex\plugins\.plugin-appserver\codex.exe"

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Write-RepairLog {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Invoke-CodexPlugin {
    param([string[]]$Arguments)
    Write-RepairLog ("RUN " + ($Arguments -join " "))
    $output = & $cli @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    foreach ($line in $output) {
        Write-RepairLog ([string]$line)
    }
    Write-RepairLog "EXIT $exitCode"
    return $exitCode
}

Write-RepairLog "Waiting for Codex main PID $MainPid to exit"
while (Get-Process -Id $MainPid -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 1
}

Start-Sleep -Seconds 3
Get-Process -Name "extension-host", "node_repl" -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue

Write-RepairLog "Codex exited; starting bundled plugin replacement"
$failed = $false

foreach ($plugin in @("chrome@openai-bundled", "computer-use@openai-bundled")) {
    if ((Invoke-CodexPlugin @("plugin", "remove", $plugin, "--json")) -ne 0) {
        $failed = $true
    }
}

foreach ($plugin in @("chrome@openai-bundled", "computer-use@openai-bundled")) {
    if ((Invoke-CodexPlugin @("plugin", "add", $plugin, "--json")) -ne 0) {
        $failed = $true
    }
}

Invoke-CodexPlugin @("plugin", "list") | Out-Null
if ($failed) {
    Write-RepairLog "REPAIR_FAILED"
    exit 1
}

Write-RepairLog "REPAIR_COMPLETE"
exit 0
