# Task 644 step V (as Tasks 640 and 643), on the VM (run over gcloud compute ssh as the VM's admin user; no secret is read or written):
# Python 3.13.7 x64, Node 22.18.0 x64, Git for Windows 2.47.1 (each downloaded from its project's own site, Authenticode
# signature checked, Node's SHA-256 too), Developer Mode, @openai/codex at the pinned version, graftling's candidate from
# the uploaded bundle in a venv with the CI pins, Codex's config.toml (provider only) and the versions record.
# Last line: PROVISION PASS, or PROVISION FAIL: <reason>.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = 'C:\v644'
$Dl = Join-Path $Root 'downloads'
New-Item -ItemType Directory -Force -Path $Dl | Out-Null
$Settings = Get-Content -Raw -Encoding UTF8 (Join-Path $Root 'settings.json') | ConvertFrom-Json
$PyVer = '3.13.7'; $NodeVer = '22.18.0'; $GitVer = '2.47.1'
$NodeSha = 'dffd8e34d8eb1a1a2e6f5e6f129c4b1b8a34aa54e02799007adc99d73efac75c'  # node-v22.18.0-x64.msi, SHASUMS256.txt
$Py = 'C:\Program Files\Python313\python.exe'
$Node = 'C:\Program Files\nodejs\node.exe'
$Npm = 'C:\Program Files\nodejs\npm.cmd'
$Git = 'C:\Program Files\Git\cmd\git.exe'
$Venv = Join-Path $Root 'venv'
$Graft = Join-Path $Root 'graftling'

# Functions whose value is used write their log lines straight to the console ([Console]::Out), never to the
# output stream, so they return exactly one value (correction 2: Fetch returned its log line and the path).
function Say($text) { [Console]::Out.WriteLine("== $text") }
function Fail($text) { [Console]::Out.WriteLine("PROVISION FAIL: $text"); exit 1 }
function Fetch($url, $file, $signer) {
  $path = Join-Path $Dl $file
  if (-not (Test-Path $path)) {
    try { Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $path } catch { Fail "download $file : $($_.Exception.Message)" }
  }
  $sig = Get-AuthenticodeSignature -FilePath $path
  if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notlike "*$signer*") {
    Remove-Item -Force $path  # a bad or partial download must not be reused by a rerun
    Fail "$file signature $($sig.Status), signer $($sig.SignerCertificate.Subject)"
  }
  [Console]::Out.WriteLine("  $file : signature Valid, signer $($sig.SignerCertificate.Subject)")
  return $path
}
function Run($file, $arguments) {
  # The handle is read before waiting, so ExitCode is filled in (it can stay empty otherwise); the exit code is
  # taken from the process object, never from $LASTEXITCODE.
  $p = Start-Process -FilePath $file -ArgumentList $arguments -PassThru -NoNewWindow
  $null = $p.Handle
  $p.WaitForExit()
  return $p.ExitCode
}

Say "Python $PyVer"
if (-not (Test-Path $Py)) {
  $exe = Fetch "https://www.python.org/ftp/python/$PyVer/python-$PyVer-amd64.exe" "python-$PyVer-amd64.exe" 'Python Software Foundation'
  $code = Run $exe @('/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0', 'Include_launcher=0')
  if ($code -ne 0) { Fail "Python installer exit $code" }
}
Say "Node $NodeVer"
if (-not (Test-Path $Node)) {
  $msi = Fetch "https://nodejs.org/dist/v$NodeVer/node-v$NodeVer-x64.msi" "node-v$NodeVer-x64.msi" 'OpenJS Foundation'
  if ((Get-FileHash -Algorithm SHA256 $msi).Hash.ToLower() -ne $NodeSha) { Fail 'node msi SHA-256 differs from SHASUMS256.txt' }
  $code = Run 'msiexec.exe' @('/i', "`"$msi`"", '/qn', '/norestart')
  if ($code -ne 0 -and $code -ne 3010) { Fail "Node installer exit $code" }
}
Say "Git for Windows $GitVer"
if (-not (Test-Path $Git)) {
  $exe = Fetch "https://github.com/git-for-windows/git/releases/download/v$GitVer.windows.1/Git-$GitVer-64-bit.exe" "Git-$GitVer-64-bit.exe" 'Johannes Schindelin'
  $code = Run $exe @('/VERYSILENT', '/NORESTART', '/NOCANCEL', '/SP-', '/SUPPRESSMSGBOXES')
  if ($code -ne 0) { Fail "Git installer exit $code" }
}
$env:Path = "C:\Program Files\Python313;C:\Program Files\nodejs;$env:APPDATA\npm;C:\Program Files\Git\cmd;$env:Path"
$env:PYTHONUTF8 = '1'

Say 'Developer Mode (symbolic links without elevation; graftling links Codex rollouts, decision 4)'
& reg.exe add 'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' /v AllowDevelopmentWithoutDevLicense /t REG_DWORD /d 1 /f | Out-Null
if ($LASTEXITCODE -ne 0) { Fail 'Developer Mode registry value not set' }

Say "@openai/codex@$($Settings.codex_version)"
& $Npm install -g "@openai/codex@$($Settings.codex_version)" --no-fund --no-audit
if ($LASTEXITCODE -ne 0) { Fail "npm install exit $LASTEXITCODE" }

Say "graftling $($Settings.candidate) from the bundle"
if (-not (Test-Path (Join-Path $Graft '.git'))) {
  & $Git -c core.symlinks=true clone --no-checkout (Join-Path $Root 'graftling.bundle') $Graft
  if ($LASTEXITCODE -ne 0) { Fail 'git clone from the bundle failed' }
}
& $Git -C $Graft -c core.symlinks=true checkout --detach $Settings.candidate
if ($LASTEXITCODE -ne 0) { Fail 'checkout of the candidate failed' }
$head = (& $Git -C $Graft rev-parse HEAD).Trim()
if ($head -ne $Settings.candidate) { Fail "graftling HEAD $head is not the candidate" }

Say 'venv: graftling (--no-deps -e) and the CI pins'
if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) { & $Py -m venv $Venv; if ($LASTEXITCODE -ne 0) { Fail 'venv failed' } }
$VPy = Join-Path $Venv 'Scripts\python.exe'
& $VPy -m pip install --disable-pip-version-check -q --no-deps -e $Graft
if ($LASTEXITCODE -ne 0) { Fail 'pip install graftling failed' }
& $VPy -m pip install --disable-pip-version-check -q PyYAML==6.0.2 websockets==15.0.1 pytest==8.3.5
if ($LASTEXITCODE -ne 0) { Fail 'pip install of the CI pins failed' }

Say 'Codex config.toml (provider only, env_key names the variable; no secret) and the versions record'
& $VPy (Join-Path $Root 'drive644.py') config
if ($LASTEXITCODE -ne 0) { Fail 'config.toml not written' }
& $VPy (Join-Path $Root 'drive644.py') versions V
if ($LASTEXITCODE -ne 0) { Fail 'versions record failed' }
[Console]::Out.WriteLine('PROVISION PASS')
