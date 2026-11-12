# PowerShell script to register right-click context menu for .glb and .gltf files
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$cliPath = Join-Path $scriptDir "cli.py"

$regRoot = "HKCU:\Software\Classes\SystemFileAssociations"

foreach ($ext in @(".glb", ".gltf")) {
    $keyPath = "$regRoot\$ext\shell\GLB2Print"
    $cmdPath = "$keyPath\command"

    New-Item -Path $keyPath -Force | Out-Null
    Set-ItemProperty -Path $keyPath -Name "(Default)" -Value "Prepare for 3D Printing (GLB2Print)"
    Set-ItemProperty -Path $keyPath -Name "Icon" -Value "imageres.dll,242"

    New-Item -Path $cmdPath -Force | Out-Null
    $cmdVal = "python `"$cliPath`" `"%1`" -t 250000 -r 1024 -f both"
    Set-ItemProperty -Path $cmdPath -Name "(Default)" -Value $cmdVal
}

Write-Host "GLB2Print context menu installed successfully!" -ForegroundColor Green
Write-Host "You can now right-click any .glb or .gltf file in Windows Explorer -> 'Prepare for 3D Printing (GLB2Print)'"
