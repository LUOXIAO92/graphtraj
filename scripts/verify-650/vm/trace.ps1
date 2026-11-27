# Task 650, on the VM: a process trace while one host run lasts (started and stopped by drive650.py's Tracer, elevated,
# in the case's scheduled task). Every process start (Win32_ProcessStartTrace: pid, parent pid, name; and, while the
# process still lives, its ExecutablePath and CommandLine from Win32_Process) and every stop (Win32_ProcessStopTrace:
# exit status) is one JSON line in -Out. The first line is {"kind":"ready"}; it ends when -StopFile exists.
# Nothing is changed on the machine (no audit policy, no registry); the subscriptions end with this process.
param([Parameter(Mandatory = $true)][string]$Out, [Parameter(Mandatory = $true)][string]$StopFile)
$ErrorActionPreference = 'Continue'
$global:V650Writer = [IO.StreamWriter]::new($Out, $true, [Text.UTF8Encoding]::new($false))
$global:V650Writer.AutoFlush = $true
function global:V650Line($table) { $global:V650Writer.WriteLine(($table | ConvertTo-Json -Compress)) }
Register-CimIndicationEvent -ClassName Win32_ProcessStartTrace -SourceIdentifier v650start -Action {
  $e = $EventArgs.NewEvent
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($e.ProcessID)" -ErrorAction SilentlyContinue
  V650Line @{ kind = 'start'; t = (Get-Date).ToString('o'); pid = [int]$e.ProcessID; ppid = [int]$e.ParentProcessID;
              name = [string]$e.ProcessName; exe = [string]$p.ExecutablePath; cmd = [string]$p.CommandLine }
} | Out-Null
Register-CimIndicationEvent -ClassName Win32_ProcessStopTrace -SourceIdentifier v650stop -Action {
  $e = $EventArgs.NewEvent
  V650Line @{ kind = 'stop'; t = (Get-Date).ToString('o'); pid = [int]$e.ProcessID; ppid = [int]$e.ParentProcessID;
              name = [string]$e.ProcessName; exit = [int64]$e.ExitStatus }
} | Out-Null
V650Line @{ kind = 'ready'; t = (Get-Date).ToString('o') }
while (-not (Test-Path -LiteralPath $StopFile)) { Wait-Event -Timeout 1 | Out-Null }
Unregister-Event -SourceIdentifier v650start -ErrorAction SilentlyContinue
Unregister-Event -SourceIdentifier v650stop -ErrorAction SilentlyContinue
V650Line @{ kind = 'end'; t = (Get-Date).ToString('o') }
$global:V650Writer.Close()
