# Puts an "H9 Voice Transcriber" shortcut on the desktop.
# It points at dist\H9 Transcriber.exe when that build exists, otherwise at
# H9 Transcriber.bat, which builds the environment on its first run.

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$exe  = Join-Path $root 'dist\H9 Transcriber.exe'
$bat  = Join-Path $root 'H9 Transcriber.bat'
$icon = Join-Path $root 'assets\icon.ico'

if (Test-Path -LiteralPath $exe) {
    $target = $exe
    $style  = 1            # normal window
} elseif (Test-Path -LiteralPath $bat) {
    $target = $bat
    $style  = 7            # minimized, so the console does not flash open
} else {
    throw "Neither 'dist\H9 Transcriber.exe' nor 'H9 Transcriber.bat' was found in $root"
}

$desktop  = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktop 'H9 Voice Transcriber.lnk'

$shell    = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath       = $target
$shortcut.WorkingDirectory = $root
$shortcut.Description      = 'Offline speech to text with Whisper large-v3'
$shortcut.WindowStyle      = $style
if (Test-Path -LiteralPath $icon) {
    $shortcut.IconLocation = "$icon,0"
}
$shortcut.Save()

Write-Host "Shortcut created: $linkPath"
Write-Host "It starts:        $target"
