# Task 643 step I, on the VM (run over gcloud compute ssh as the VM user, elevated): give this user a NEW random
# password generated here (never printed, never sent anywhere, never written outside the Winlogon value Windows reads
# for automatic logon) and configure Winlogon automatic logon for this user, so that after the reboot step I starts
# the user has an interactive console session. Nothing else is changed: UAC, the firewall, RDP and every other
# security setting stay as they are. The legal-notice values (which would hold an automatic logon at a dialog) are
# only reported. drive643.py scan treats the password like the provider key (a hit fails the scan, nothing leaves).
# Last line: AUTOLOGON SET, or AUTOLOGON FAIL: <reason>.
$ErrorActionPreference = 'Stop'
$Winlogon = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
$User = $env:USERNAME
try {
  # 24 characters from a cryptographic generator, with each class present (local password complexity policy).
  $Upper = 'ABCDEFGHJKLMNPQRSTUVWXYZ'; $Lower = 'abcdefghijkmnopqrstuvwxyz'; $Digit = '23456789'; $Mark = '#%+-.:=@_'
  $All = $Upper + $Lower + $Digit + $Mark
  $Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  function Pick($set) { $b = New-Object byte[] 4; $Rng.GetBytes($b); return $set[[BitConverter]::ToUInt32($b, 0) % $set.Length] }
  $Chars = @((Pick $Upper), (Pick $Lower), (Pick $Digit), (Pick $Mark))
  for ($i = 0; $i -lt 20; $i++) { $Chars += (Pick $All) }
  $Plain = -join ($Chars | Sort-Object { $b = New-Object byte[] 4; $Rng.GetBytes($b); [BitConverter]::ToUInt32($b, 0) })
  Set-LocalUser -Name $User -Password (ConvertTo-SecureString -String $Plain -AsPlainText -Force)
  [Console]::Out.WriteLine('  password: a new random one set for the VM user (24 characters; not printed)')
  Set-ItemProperty -Path $Winlogon -Name AutoAdminLogon -Value '1' -Type String
  Set-ItemProperty -Path $Winlogon -Name DefaultUserName -Value $User -Type String
  Set-ItemProperty -Path $Winlogon -Name DefaultDomainName -Value $env:COMPUTERNAME -Type String
  Set-ItemProperty -Path $Winlogon -Name DefaultPassword -Value $Plain -Type String
  Remove-ItemProperty -Path $Winlogon -Name AutoLogonCount -ErrorAction SilentlyContinue
  $Plain = $null
  $Back = Get-ItemProperty -Path $Winlogon
  [Console]::Out.WriteLine("  Winlogon: AutoAdminLogon $($Back.AutoAdminLogon); DefaultUserName is this user: $($Back.DefaultUserName -eq $User); DefaultDomainName is this computer: $($Back.DefaultDomainName -eq $env:COMPUTERNAME); DefaultPassword set: $([bool]$Back.DefaultPassword)")
  $Policy = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -ErrorAction SilentlyContinue
  $Caption = "$($Policy.legalnoticecaption)"; $Text = "$($Policy.legalnoticetext)"
  [Console]::Out.WriteLine("  legal notice (reported, not changed): caption $(if ($Caption) { 'set' } else { 'empty' }), text $(if ($Text) { 'set' } else { 'empty' }); UAC EnableLUA $($Policy.EnableLUA) (not changed)")
  if ($Back.AutoAdminLogon -ne '1' -or $Back.DefaultUserName -ne $User -or -not $Back.DefaultPassword) { throw 'the Winlogon values did not read back' }
  [Console]::Out.WriteLine('AUTOLOGON SET')
} catch {
  [Console]::Out.WriteLine("AUTOLOGON FAIL: $($_.Exception.Message)")
  exit 1
}
