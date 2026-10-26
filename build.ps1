param([string]$InnoCompiler = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m PyInstaller --clean --noconfirm --onefile --windowed --name ModelKeeperHost --exclude-module desktop --exclude-module floating --exclude-module PySide6 --add-data 'extension;extension' native_host.py
if ($LASTEXITCODE -ne 0) { throw 'Native host build failed' }
python -m PyInstaller --clean --noconfirm --onedir --windowed --name ModelKeeper --exclude-module tkinter --exclude-module floating --exclude-module numpy --exclude-module PIL --add-data 'extension;extension' --add-data 'desktop_ui;desktop_ui' --add-data 'runtime_manifest.json;.' --add-data 'runtime_seed;runtime_seed' app.py
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
# Qt 6.12 uses the stable Windows ICU API. PyInstaller can collect an
# unrelated ICU 78 from PATH, whose versioned exports shadow System32 ICU.
foreach ($name in @('icuuc.dll','icudt78.dll')) {
    $target = Join-Path $PSScriptRoot "dist/ModelKeeper/_internal/$name"
    if (Test-Path -LiteralPath $target) {
        $resolved = (Resolve-Path -LiteralPath $target).Path
        $bundle = (Resolve-Path -LiteralPath 'dist/ModelKeeper/_internal').Path
        if ([IO.Path]::GetDirectoryName($resolved) -ne $bundle) { throw 'Unexpected ICU path' }
        $quarantine=Join-Path $PSScriptRoot 'build/icu-excluded'
        New-Item -ItemType Directory -Path $quarantine -Force | Out-Null
        Move-Item -LiteralPath $resolved -Destination (Join-Path $quarantine $name) -Force
    }
}
Copy-Item -LiteralPath 'dist/ModelKeeperHost.exe' -Destination 'dist/ModelKeeper/ModelKeeperHost.exe' -Force
Copy-Item -LiteralPath 'THIRD_PARTY.md' -Destination 'dist/ModelKeeper/THIRD_PARTY.md' -Force
Copy-Item -LiteralPath 'LICENSES' -Destination 'dist/ModelKeeper/LICENSES' -Recurse -Force
if (!$InnoCompiler) {
    foreach ($candidate in @('C:/Program Files (x86)/Inno Setup 6/ISCC.exe','C:/Program Files/Inno Setup 7/ISCC.exe','../tools/inno/ISCC.exe')) {
        if (Test-Path -LiteralPath $candidate) { $InnoCompiler=$candidate; break }
    }
}
if (!$InnoCompiler) { throw 'Inno Setup compiler not found. Pass -InnoCompiler with the ISCC.exe path.' }
& $InnoCompiler 'installer.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
Get-FileHash -LiteralPath 'release/ModelKeeper-Setup.exe' -Algorithm SHA256 | ForEach-Object { $_.Hash.ToLower() + '  ModelKeeper-Setup.exe' } | Set-Content -LiteralPath 'release/SHA256SUMS.txt' -Encoding ascii
Write-Output 'Built release/ModelKeeper-Setup.exe'
