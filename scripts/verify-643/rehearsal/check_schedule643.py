"""Task 643 rehearsal (correction 1): string checks of the PowerShell drive643.task_script generates for the
scheduled task (there is no pwsh here). Usage: V643_HOME=<dir> python3 -I check_schedule643.py <verify-643/vm>."""
import sys
sys.path.insert(0, sys.argv[1])
import drive643
text = drive643.task_script('B', 'v643-B', r'C:\v643\drive643.py', 20)
checks = {
    'principal from the token SID ([Security.Principal.WindowsIdentity]::GetCurrent() ... .User.Value)':
        '[Security.Principal.WindowsIdentity]::GetCurrent()' in text and '$sid = $me.User.Value' in text,
    'New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Highest':
        '-UserId $sid -LogonType Interactive -RunLevel Highest' in text,
    'no USERDOMAIN\\USERNAME principal any more': "$env:USERDOMAIN + '\\'" not in text and '-UserId ($env:' not in text,
    'printed: booleans only (two PRINCIPAL lines, each a [bool] or -eq expression)':
        [l for l in text.splitlines() if l.startswith("'PRINCIPAL")] == [
            "'PRINCIPAL from the token (SID of the current identity): ' + [bool]($sid -like 'S-1-5-*')",
            "'PRINCIPAL USERDOMAIN equals COMPUTERNAME: ' + ($env:USERDOMAIN -eq $env:COMPUTERNAME)"],
    'neither the name nor the SID is printed': not any(l.strip() in ('$sid', '$me.Name', '$env:USERNAME') for l in text.splitlines()),
    'task registered and started by name v643-B': "Register-ScheduledTask -TaskName 'v643-B'" in text and "Start-ScheduledTask -TaskName 'v643-B'" in text,
    'stops on the first error': text.startswith("$ErrorActionPreference = 'Stop'"),
}
for name, ok in checks.items():
    print(f'{"yes" if ok else "NO "}  {name}')
print('--- the generated text:')
print(text)
print(f'SCHEDULE-TEXT {"PASS" if all(checks.values()) else "FAIL"}: {sum(checks.values())} of {len(checks)} checks')
