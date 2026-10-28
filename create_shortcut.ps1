$ErrorActionPreference = 'Stop'
$packageRoot = $PSScriptRoot
$desktopFolder = [Environment]::GetFolderPath('Desktop')
$shortcutName = 'OpenDesk Mail'
$shortcutPath = Join-Path $desktopFolder ($shortcutName + '.lnk')
$number = 2
while (Test-Path -LiteralPath $shortcutPath) {
    $shortcutPath = Join-Path $desktopFolder ($shortcutName + ' ' + $number + '.lnk')
    $number++
}
$shellObject = New-Object -ComObject WScript.Shell
$link = $shellObject.CreateShortcut($shortcutPath)
$link.TargetPath = Join-Path $packageRoot 'launch.bat'
$link.WorkingDirectory = $packageRoot
$link.Description = 'Standalone local mail tool'
$link.Save()
