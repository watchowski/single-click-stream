# Makes the desktop shortcuts for Single Click Stream.
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pyw) { $pyw = Join-Path (Split-Path (Get-Command python.exe).Source) 'pythonw.exe' }
$desktop = [Environment]::GetFolderPath('Desktop')
$ws = New-Object -ComObject WScript.Shell
function New-AppShortcut($name, $arguments, $icon) {
  $s = $ws.CreateShortcut((Join-Path $desktop "$name.lnk"))
  $s.TargetPath = $pyw
  $s.Arguments = $arguments
  $s.WorkingDirectory = $dir
  $s.IconLocation = $icon
  $s.Save()
  Write-Output "Created: $name"
}
New-AppShortcut 'Go Live on YouTube' ('"' + (Join-Path $dir 'streamer.py') + '"') (Join-Path $dir 'golive.ico')
New-AppShortcut 'Stream Control Panel' ('"' + (Join-Path $dir 'streamer.py') + '" --panel') (Join-Path $dir 'panel.ico')
