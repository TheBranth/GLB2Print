# PowerShell script to register right-click context menu for .glb and .gltf files
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$guiPath = Join-Path $scriptDir "app_gui.py"

$regRoot = "HKCU:\Software\Classes\SystemFileAssociations"

foreach ($ext in @(".glb", ".gltf")) {
    $keyPath = "$regRoot\$ext\shell\GLB2Print"
    $cmdPath = "$keyPath\command"

    New-Item -Path $keyPath -Force | Out-Null
    Set-ItemProperty -Path $keyPath -Name "(Default)" -Value "Open in GLB2Print (3D View & Split)"
    Set-ItemProperty -Path $keyPath -Name "Icon" -Value "imageres.dll,242"

    New-Item -Path $cmdPath -Force | Out-Null
    $cmdVal = "python `"$guiPath`" `"%1`""
    Set-ItemProperty -Path $cmdPath -Name "(Default)" -Value $cmdVal
}

Write-Host "GLB2Print context menu installed successfully!" -ForegroundColor Green
Write-Host "You can now right-click any .glb or .gltf file in Windows Explorer -> 'Open in GLB2Print (3D View & Split)'"
