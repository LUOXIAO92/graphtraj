# Task 640 step K, on the VM: read the temporary key as ONE line from stdin (the ssh session's), store it as this
# Windows user's environment variable named by settings.json (provider.key_env), read it back, and print only that it
# was stored and its length. The value is never printed, logged or written to a file here.
$ErrorActionPreference = 'Stop'
$Settings = Get-Content -Raw -Encoding UTF8 'C:\v640\settings.json' | ConvertFrom-Json
$Name = $Settings.provider.key_env
$Value = [Console]::In.ReadLine()
if ($null -eq $Value -or $Value.Trim().Length -eq 0) { Write-Output 'KEY FAIL: nothing arrived on stdin; nothing stored'; exit 1 }
$Value = $Value.Trim()
[Environment]::SetEnvironmentVariable($Name, $Value, 'User')
$Back = [Environment]::GetEnvironmentVariable($Name, 'User')
if ($Back -ne $Value) { Write-Output 'KEY FAIL: the stored value does not read back'; exit 1 }
Write-Output ('KEY STORED for this Windows user as a User environment variable (length {0}); the value is not printed' -f $Value.Length)
