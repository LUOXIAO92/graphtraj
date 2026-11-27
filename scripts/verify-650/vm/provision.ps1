# Task 650 step V (from Task 644's), on the VM (run over gcloud compute ssh as the VM's user; no secret is read or written):
# Git for Windows 2.47.1 and Node 24.22.3 x64 (downloaded from their projects' own sites, Authenticode checked, Node's
# SHA-256 too), uv 0.13.10 (GitHub release zip, SHA-256 pinned here) into %USERPROFILE%\.local\bin, Developer Mode,
# graftling's candidate from the uploaded bundle installed as its README says (uv tool install --managed-python, from
# the bundle's checkout), Claude Code by its native installer at the pinned version (claude.exe, Authenticode checked),
# pnpm, Pi and DSH from npm at the pinned versions (DSH's install time measured: D1), graftling's Pi package installed
# with `pi install`, graftling's DSH plugin added to the headless profile with `dsh plugin add`, driver.cmd, and the
# versions record. Everything already installed at its pin is skipped, so a rerun repeats only idempotent work.
# Last line: PROVISION PASS, or PROVISION FAIL: <reason>.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = 'C:\v650'
$Dl = Join-Path $Root 'downloads'
$Out = Join-Path $Root 'out\V'
New-Item -ItemType Directory -Force -Path $Dl, $Out | Out-Null
$Settings = Get-Content -Raw -Encoding UTF8 (Join-Path $Root 'settings.json') | ConvertFrom-Json
$Pins = $Settings.pins
$NodeVer = '24.22.3'; $GitVer = '2.47.1'; $UvVer = '0.13.10'
$NodeSha = '4a1ab5bdec5434bae58efae6c3e5077a011f6f1e76d2b47b7b10af043f7db545'  # node-v24.22.3-x64.msi, SHASUMS256.txt
$UvSha = '297b3881fe1adfb922becc2c1613202abb41dc83ea5ff43d472aa087ca1f8683'    # uv-x86_64-pc-windows-msvc.zip, .sha256
$Node = 'C:\Program Files\nodejs\node.exe'
$Npm = 'C:\Program Files\nodejs\npm.cmd'
$Git = 'C:\Program Files\Git\cmd\git.exe'
$Bin = Join-Path $env:USERPROFILE '.local\bin'
$Uv = Join-Path $Bin 'uv.exe'
$Claude = Join-Path $Bin 'claude.exe'
$NpmBin = Join-Path $env:APPDATA 'npm'
$Graft = Join-Path $Root 'graftling'

# Functions whose value is used write their log lines straight to the console ([Console]::Out), never to the
# output stream, so they return exactly one value (644 correction 2).
function Say($text) { [Console]::Out.WriteLine("== $text") }
function Fail($text) { [Console]::Out.WriteLine("PROVISION FAIL: $text"); exit 1 }
function Fetch($url, $file) {
  $path = Join-Path $Dl $file
  if (-not (Test-Path $path)) {
    try { Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $path } catch { Fail "download $file : $($_.Exception.Message)" }
  }
  return $path
}
function Signed($path, $signer) {
  $sig = Get-AuthenticodeSignature -FilePath $path
  if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notlike "*$signer*") {
    Remove-Item -Force $path -ErrorAction SilentlyContinue  # a bad or partial download must not be reused by a rerun
    Fail "$(Split-Path -Leaf $path) signature $($sig.Status), signer $($sig.SignerCertificate.Subject)"
  }
  [Console]::Out.WriteLine("  $(Split-Path -Leaf $path) : signature Valid, signer $($sig.SignerCertificate.Subject)")
}
function Sha($path, $want) {
  if ((Get-FileHash -Algorithm SHA256 $path).Hash.ToLower() -ne $want) {
    Remove-Item -Force $path -ErrorAction SilentlyContinue
    Fail "$(Split-Path -Leaf $path) SHA-256 differs from the pinned one"
  }
}
function Run($file, $arguments) {
  # The handle is read before waiting, so ExitCode is filled in; the exit code comes from the process object.
  $p = Start-Process -FilePath $file -ArgumentList $arguments -PassThru -NoNewWindow
  $null = $p.Handle
  $p.WaitForExit()
  return $p.ExitCode
}
# Logged runs: the command's whole output goes to out\V\<log>, its last lines to the console; returns the exit code.
function Logged($log, [scriptblock]$block) {
  $path = Join-Path $Out $log
  & $block *> $path
  $code = $LASTEXITCODE
  Get-Content -Tail 4 $path | ForEach-Object { [Console]::Out.WriteLine("  | $_") }
  return $code
}
function NpmVersion($package) {
  $dir = Join-Path $NpmBin "node_modules\$package\package.json"
  if (Test-Path $dir) { return (Get-Content -Raw $dir | ConvertFrom-Json).version }
  return ''
}

Say "Git for Windows $GitVer"
if (-not (Test-Path $Git)) {
  $exe = Fetch "https://github.com/git-for-windows/git/releases/download/v$GitVer.windows.1/Git-$GitVer-64-bit.exe" "Git-$GitVer-64-bit.exe"
  Signed $exe 'Johannes Schindelin'
  $code = Run $exe @('/VERYSILENT', '/NORESTART', '/NOCANCEL', '/SP-', '/SUPPRESSMSGBOXES')
  if ($code -ne 0) { Fail "Git installer exit $code" }
}
Say "Node $NodeVer"
$have = if (Test-Path $Node) { (& $Node --version).Trim() } else { '' }
if ($have -ne "v$NodeVer") {
  $msi = Fetch "https://nodejs.org/dist/v$NodeVer/node-v$NodeVer-x64.msi" "node-v$NodeVer-x64.msi"
  Sha $msi $NodeSha
  Signed $msi 'OpenJS Foundation'
  $code = Run 'msiexec.exe' @('/i', "`"$msi`"", '/qn', '/norestart')
  if ($code -ne 0 -and $code -ne 3010) { Fail "Node installer exit $code" }
}
Say "uv $UvVer"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
$have = if (Test-Path $Uv) { (& $Uv --version) -join ' ' } else { '' }
if ($have -notlike "uv $UvVer*") {
  $zip = Fetch "https://github.com/astral-sh/uv/releases/download/$UvVer/uv-x86_64-pc-windows-msvc.zip" "uv-$UvVer-x86_64-pc-windows-msvc.zip"
  Sha $zip $UvSha
  Expand-Archive -Force -Path $zip -DestinationPath $Bin
}
$env:Path = "$Bin;C:\Program Files\nodejs;$NpmBin;C:\Program Files\Git\cmd;$env:Path"
# The user's PATH gets the same directories, so the console session (step I logs it on later) finds them too.
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
foreach ($dir in @($Bin, $NpmBin)) { if (($userPath -split ';') -notcontains $dir) { $userPath = "$dir;$userPath" } }
[Environment]::SetEnvironmentVariable('Path', $userPath, 'User')
$env:PYTHONUTF8 = '1'
$env:DISABLE_AUTOUPDATER = '1'

Say 'Developer Mode (symbolic links without elevation, as Tasks 640-644 had)'
& reg.exe add 'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' /v AllowDevelopmentWithoutDevLicense /t REG_DWORD /d 1 /f | Out-Null
if ($LASTEXITCODE -ne 0) { Fail 'Developer Mode registry value not set' }

Say "graftling $($Settings.candidate) from the bundle, installed with uv tool install --managed-python (README)"
if (-not (Test-Path (Join-Path $Graft '.git'))) {
  & $Git -c core.symlinks=true clone --no-checkout (Join-Path $Root 'graftling.bundle') $Graft
  if ($LASTEXITCODE -ne 0) { Fail 'git clone from the bundle failed' }
}
& $Git -C $Graft -c core.symlinks=true checkout --detach $Settings.candidate
if ($LASTEXITCODE -ne 0) { Fail 'checkout of the candidate failed' }
$head = (& $Git -C $Graft rev-parse HEAD).Trim()
if ($head -ne $Settings.candidate) { Fail "graftling HEAD $head is not the candidate" }
$ToolDir = ((& $Uv tool dir) | Select-Object -Last 1).Trim()
$VenvPy = Join-Path $ToolDir 'graftling\Scripts\python.exe'
$installed = if (Test-Path $VenvPy) { (& $VenvPy -c 'import graftling, pathlib; print(pathlib.Path(graftling.__file__).parent)') } else { '' }
if (-not $installed) {
  $code = Logged 'uv-tool-install.txt' { & $Uv tool install --managed-python $Graft }
  if ($code -ne 0 -or -not (Test-Path $VenvPy)) { Fail "uv tool install exit $code (out\V\uv-tool-install.txt)" }
}
& $VenvPy -c "import graftling, sys; print('  graftling', graftling.__version__, 'on', sys.version.split()[0], 'venv', sys.prefix)"
if ($LASTEXITCODE -ne 0) { Fail 'the uv tool venv does not import graftling' }
Set-Content -Encoding ASCII -Path (Join-Path $Root 'driver.cmd') -Value @('@echo off', 'set PYTHONUTF8=1', "`"$VenvPy`" `"$Root\drive650.py`" %*")
[Console]::Out.WriteLine("  driver.cmd runs drive650.py on the uv tool venv's python")

Say "Claude Code $($Pins.claude) by the native installer"
$have = if (Test-Path $Claude) { ((& $Claude --version) -join ' ') } else { '' }
if ($have -notlike "$($Pins.claude)*") {
  $script = Join-Path $Dl 'claude-install.ps1'
  try { Invoke-WebRequest -UseBasicParsing -Uri 'https://claude.ai/install.ps1' -OutFile $script } catch { Fail "Claude Code installer download: $($_.Exception.Message)" }
  $code = Logged 'claude-install.txt' { & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script $Pins.claude }
  if ($code -ne 0 -or -not (Test-Path $Claude)) { Fail "Claude Code native installer exit $code (out\V\claude-install.txt)" }
}
# The installer checks claude.exe's SHA-256 against its release manifest; the signature is reported, not required.
$sig = Get-AuthenticodeSignature -FilePath $Claude
[Console]::Out.WriteLine("  claude.exe signature: $($sig.Status), signer $($sig.SignerCertificate.Subject)")
$have = ((& $Claude --version) -join ' ')
if ($have -notlike "$($Pins.claude)*") { Fail "claude.exe reports '$have', not $($Pins.claude)" }
[Console]::Out.WriteLine("  claude.exe: $have")

Say "pnpm $($Pins.pnpm) and Pi $($Pins.pi) from npm"
foreach ($pair in @(@('pnpm', $Pins.pnpm), @('@earendil-works/pi-coding-agent', $Pins.pi))) {
  if ((NpmVersion $pair[0]) -ne $pair[1]) {
    $code = Logged "npm-$(($pair[0] -replace '[@/]', '_')).txt" { & $Npm install -g "$($pair[0])@$($pair[1])" --no-fund --no-audit }
    if ($code -ne 0) { Fail "npm install $($pair[0]) exit $code" }
  }
}
Say "DSH $($Pins.dsh) from npm (D1: install time; CI took 18 min)"
$defender = try { (Get-MpComputerStatus -ErrorAction Stop).RealTimeProtectionEnabled } catch { "unknown ($($_.Exception.Message))" }
if ((NpmVersion '@deepseek-ai/dsh') -ne $Pins.dsh) {
  $code = 0
  $time = Measure-Command { $script:code = Logged 'npm-dsh.txt' { & $Npm install -g "@deepseek-ai/dsh@$($Pins.dsh)" --no-fund --no-audit } }
  if ($code -ne 0) { Fail "npm install @deepseek-ai/dsh exit $code (out\V\npm-dsh.txt)" }
  $summary = (Select-String -Path (Join-Path $Out 'npm-dsh.txt') -Pattern 'added \d+ packages' | Select-Object -Last 1).Line
  @{ seconds = [math]::Round($time.TotalSeconds, 1); npm_summary = "$summary"; realtime_protection = "$defender";
     node = (& $Node --version).Trim() } | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Out 'd1.json')
  [Console]::Out.WriteLine("  D1: $([math]::Round($time.TotalMinutes, 1)) min; npm: $summary; real-time protection: $defender")
} else {
  [Console]::Out.WriteLine('  DSH already at the pin (D1 is in out\V\d1.json from the first V)')
}
$where = (& where.exe dsh) -join ', '
[Console]::Out.WriteLine("  where dsh: $where")

# No double quote inside a native argument: Windows PowerShell 5.1 drops them (correction 2; line 129's form).
$Site = ([string](& $VenvPy -c "import sysconfig; print(sysconfig.get_path('purelib'))")).Trim()
if (-not $Site -or -not (Test-Path -LiteralPath $Site -PathType Container)) { Fail "the uv tool venv's site-packages was not found (sysconfig purelib: '$Site')" }
foreach ($part in @('graftling\pi', 'graftling\dsh')) {
  if (-not (Test-Path -LiteralPath (Join-Path $Site $part) -PathType Container)) { Fail "$part is missing in the uv tool venv's site-packages ($Site)" }
}
Say "pi install of graftling's Pi package ($Site\graftling\pi)"
$code = Logged 'pi-install.txt' { & (Join-Path $NpmBin 'pi.cmd') install (Join-Path $Site 'graftling\pi') }
if ($code -ne 0) { Fail "pi install exit $code (out\V\pi-install.txt)" }
# Correction 2: this npm skips install scripts of global installs (`npm warn install-scripts`). The skipped names are
# recorded as an observation (DSH stays as npm installed it: no reinstall, no scripts allowed). pnpm, needed by
# `dsh plugin add`, is made runnable by running its own skipped script (preinstall/postinstall: node install.js) when
# `pnpm --version` does not answer.
$skipped = @(foreach ($log in @('npm-pnpm.txt', 'npm-_earendil-works_pi-coding-agent.txt', 'npm-dsh.txt')) {
  $path = Join-Path $Out $log
  if (Test-Path $path) {
    Select-String -Path $path -Pattern 'npm warn install-scripts\s+(\S+@\S+) \(' | ForEach-Object { "$log : $($_.Matches[0].Groups[1].Value)" }
  }
})
Set-Content -Encoding UTF8 -Path (Join-Path $Out 'npm-skipped-scripts.txt') -Value ($(if ($skipped) { $skipped } else { 'no install-scripts warning found in the npm logs' }))
[Console]::Out.WriteLine("  npm skipped install scripts of: $(($skipped | ForEach-Object { ($_ -split ' : ')[1] }) -join ', ') (out\V\npm-skipped-scripts.txt)")
$PnpmCmd = Join-Path $NpmBin 'pnpm.cmd'
function PnpmVersion {
  try { $text = ((& $PnpmCmd --version 2>&1) | Out-String).Trim() } catch { return '' }
  if ($LASTEXITCODE -eq 0 -and $text -match '^\d+\.\d+\.\d+$') { return $text }
  return ''
}
$pv = PnpmVersion
if ($pv) {
  [Console]::Out.WriteLine("  pnpm answers --version: $pv (no repair needed)")
} else {
  $PnpmDir = Join-Path $NpmBin 'node_modules\pnpm'
  $scripts = (Get-Content -Raw (Join-Path $PnpmDir 'package.json') | ConvertFrom-Json).scripts
  if ($scripts.postinstall -ne 'node install.js') { Fail "pnpm does not answer --version and its postinstall is '$($scripts.postinstall)', not 'node install.js'" }
  Push-Location $PnpmDir
  $code = Logged 'pnpm-install-js.txt' { & $Node install.js }
  Pop-Location
  $pv = PnpmVersion
  if (-not $pv) { Fail "pnpm still does not answer --version after running its skipped script 'node install.js' (exit $code; out\V\pnpm-install-js.txt)" }
  [Console]::Out.WriteLine("  pnpm repaired by its own skipped script (node install.js, exit $code): --version $pv")
}
Say "dsh plugin add of graftling's DSH plugin to the headless profile ($Site\graftling\dsh)"
$code = Logged 'dsh-plugin-add.txt' { & (Join-Path $NpmBin 'dsh.cmd') plugin --profile headless add (Join-Path $Site 'graftling\dsh') }
if ($code -ne 0) { Fail "dsh plugin add exit $code (out\V\dsh-plugin-add.txt)" }

Say 'the versions record'
& (Join-Path $Root 'driver.cmd') versions V
if ($LASTEXITCODE -ne 0) { Fail 'versions record failed' }
[Console]::Out.WriteLine('PROVISION PASS')
