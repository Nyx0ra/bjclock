param([string]$PythonExe)
$ErrorActionPreference = 'Stop'
if (-not $PythonExe) {
    $PythonExe = (Get-Command python.exe -ErrorAction Stop).Source
}
$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
& $PythonExe -c "import sys, tkinter; assert sys.version_info >= (3,9); assert sys.platform == 'win32'"
if ($LASTEXITCODE -ne 0) { throw 'A Windows Python 3.9+ installation with tkinter is required.' }
$pythonw = Join-Path (Split-Path -Parent $PythonExe) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw "Missing pythonw.exe: $pythonw" }
$dest = Join-Path $env:USERPROFILE '.bjclock'
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$script = Join-Path $dest 'bjclock.py'
if (Test-Path -LiteralPath $script) {
    & $PythonExe $script --stop
    Start-Sleep -Seconds 2
}
$source = Join-Path $PSScriptRoot 'bjclock.py'
if ([IO.Path]::GetFullPath($source) -ne [IO.Path]::GetFullPath($script)) {
    Copy-Item -LiteralPath $source -Destination $script
}
$config = Join-Path $dest 'config.json'
if (-not (Test-Path -LiteralPath $config)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Destination $config
}
# VBScript doubles literal quotes; use UTF-16 so user paths can contain Unicode.
$command = '""' + $pythonw + '"" ""' + $script + '""'
@('Set shell = CreateObject("WScript.Shell")', ('shell.Run "' + $command + ' --stop", 0, True')) |
    Set-Content -LiteralPath (Join-Path $dest 'Stop.vbs') -Encoding Unicode
@('Set shell = CreateObject("WScript.Shell")', ('shell.Run "' + $command + ' --stop", 0, True'),
  'WScript.Sleep 1500', ('shell.Run "' + $command + '", 0, False')) |
    Set-Content -LiteralPath (Join-Path $dest 'Restart.vbs') -Encoding Unicode
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Beijing Clock.lnk'))
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + $script + '"'
$shortcut.WorkingDirectory = $dest
$shortcut.WindowStyle = 7
$shortcut.Description = 'Offline Beijing UTC+8 click-through taskbar clock'
$shortcut.Save()
Start-Process -FilePath $pythonw -ArgumentList ('"' + $script + '"') -WorkingDirectory $dest -WindowStyle Hidden
Write-Host "Installed and started: $script"
Write-Host "Edit $config to adjust placement."
