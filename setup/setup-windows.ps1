$ErrorActionPreference = "Stop"

function Install-WingetPackage {
    param(
        [Parameter(Mandatory=$true)]
        [string] $Id
    )

    winget install `
        --id $Id `
        --exact `
        --source winget `
        --accept-package-agreements `
        --accept-source-agreements `
        --silent

    if ($LASTEXITCODE -ne 0) {
        throw "winget failed while installing $Id (exit code $LASTEXITCODE)"
    }
}

$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) {
    throw "winget is not installed. Install/enable App Installer from Microsoft, then rerun this script."
}

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Install-WingetPackage "Git.Git"
}

$cmake = Get-Command cmake -ErrorAction SilentlyContinue
if (-not $cmake) {
    Install-WingetPackage "Kitware.CMake"
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Install-WingetPackage "Python.Python.3.13"
}

$msys2Root = "C:\msys64"
if (-not (Test-Path $msys2Root)) {
    Install-WingetPackage "MSYS2.MSYS2"
}

$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [Environment]::GetEnvironmentVariable("Path", "User")

$bash = Join-Path $msys2Root "usr\bin\bash.exe"

if (-not (Test-Path $bash)) {
    throw "MSYS2 was installed, but bash.exe was not found at $bash"
}

& $bash -lc 'pacman --noconfirm -Syuu' 2>&1
& $bash -lc 'pacman --noconfirm -Suu' 2>&1
& $bash -lc 'pacman --noconfirm --needed -S mingw-w64-ucrt-x86_64-toolchain mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja mingw-w64-ucrt-x86_64-pkgconf mingw-w64-ucrt-x86_64-zlib mingw-w64-ucrt-x86_64-libusb' 2>&1

if ($LASTEXITCODE -ne 0) {
    throw "MSYS2 package installation failed."
}

python -m pip install --upgrade pip
python -m pip install -r ../python-tools/requirements.txt

if ($LASTEXITCODE -ne 0) {
    throw "Python package installation failed."
}

$devRoot = Join-Path $HOME "u-ndt-tools"
$picoSdk = Join-Path $devRoot "pico-sdk"

New-Item -ItemType Directory -Force -Path $devRoot | Out-Null

if (-not (Test-Path $picoSdk)) {
    git clone --recursive https://github.com/raspberrypi/pico-sdk.git $picoSdk
}

[Environment]::SetEnvironmentVariable("PICO_SDK_PATH", $picoSdk, "User")
$env:PICO_SDK_PATH = $picoSdk
