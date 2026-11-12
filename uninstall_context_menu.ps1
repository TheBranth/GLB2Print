# PowerShell script to remove right-click context menu for .glb and .gltf files
$regRoot = "HKCU:\Software\Classes\SystemFileAssociations"

foreach ($ext in @(".glb", ".gltf")) {
    $keyPath = "$regRoot\$ext\shell\GLB2Print"
    if (Test-Path $keyPath) {
        Remove-Item -Path $keyPath -Recurse -Force
    }
}

Write-Host "GLB2Print context menu removed." -ForegroundColor Yellow
