# Installs Desktop Hub:
#  1. copies wallpaper\ into Wallpaper Engine's "myprojects" as the "Desktop Hub" wallpaper
#  2. adds a Startup-folder shortcut that runs server.py with pythonw (no window) at login
#  3. starts the server now if it is not running
#  4. downloads Ultralight 1.3 the first time, builds the overlay (overlay\), adds a Startup shortcut for it too,
#     then starts it
# Run again after changing wallpaper\ or overlay\. Widgets in web\ need no reinstall.
# Remove: delete "Desktop Hub.lnk" and "Desktop Hub Overlay.lnk" from shell:startup and the myprojects\desktop_hub folder.

$ErrorActionPreference = "Stop"
$hub = $PSScriptRoot

$steam = (Get-ItemProperty "HKCU:\Software\Valve\Steam").SteamPath -replace "/", "\"
$we = Join-Path $steam "steamapps\common\wallpaper_engine\projects\myprojects\desktop_hub"
New-Item -ItemType Directory -Force $we | Out-Null
Copy-Item (Join-Path $hub "wallpaper\*") $we -Force
Write-Output "Wallpaper copied to $we"

$pyw = (& py -3.13 -c "import sys, pathlib; print(pathlib.Path(sys.executable).with_name('pythonw.exe'))").Trim()
$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Desktop Hub.lnk"
$sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$sc.TargetPath = $pyw
$sc.Arguments = "`"$(Join-Path $hub 'server.py')`""
$sc.WorkingDirectory = $hub
$sc.Description = "Desktop Hub backend for the Wallpaper Engine widget wallpaper"
$sc.Save()
Write-Output "Startup shortcut: $lnk"

$running = $false
try { $running = (Invoke-WebRequest "http://127.0.0.1:8765/api/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch {}
if (-not $running) {
    Start-Process -FilePath $pyw -ArgumentList "`"$(Join-Path $hub 'server.py')`"" -WorkingDirectory $hub
    Write-Output "Server started"
} else {
    Write-Output "Server already running"
}

# The overlay: a transparent window on monitor 2, above whatever Wallpaper Engine shows (scenes included).
# It waits for the server by itself, so the two shortcuts can start in any order.
$overlayDir = Join-Path $hub "overlay"
$overlayExe = Join-Path $overlayDir "bin\Release\net8.0-windows\hub_overlay.exe"
# Ultralight 1.3 (free for non-commercial use, see overlay\ultralight\license) isn't in the repository: fetch it once.
$ul = Join-Path $overlayDir "ultralight"
if (-not (Test-Path (Join-Path $ul "bin\WebCore.dll"))) {
    $archive = Join-Path $env:TEMP "ultralight-sdk-win-x64.7z"
    Write-Output "Downloading Ultralight (about 18 MB)..."
    # Ultralight's own "latest" link, which serves 1.3.0. The overlay is written for 1.3: say so if that changes.
    Invoke-WebRequest "https://ultralight-sdk.sfo2.cdn.digitaloceanspaces.com/ultralight-sdk-latest-win-x64.7z" -OutFile $archive -UseBasicParsing
    if ((Get-FileHash $archive).Hash -ne "4FA7AADD1E4BA4A7DC04D17B1D82B37B141C6E4E7196501150486FA6AC1635C5") {
        Write-Warning "This isn't the Ultralight 1.3.0 the overlay was made for; it may not build or run."
    }
    New-Item -ItemType Directory -Force $ul | Out-Null
    & "$env:SystemRoot\System32\tar.exe" -xf $archive -C $ul bin resources license
    if ($LASTEXITCODE -ne 0) { throw "Could not unpack $archive" }
    Remove-Item $archive
}
Get-Process hub_overlay -ErrorAction SilentlyContinue | Stop-Process -Force   # the build replaces the running exe
& dotnet build (Join-Path $overlayDir "Overlay.csproj") -c Release -nologo -v q
if ($LASTEXITCODE -ne 0) { throw "Overlay build failed" }

$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Desktop Hub Overlay.lnk"
$sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$sc.TargetPath = $overlayExe
$sc.WorkingDirectory = Split-Path $overlayExe
$sc.Description = "Desktop Hub widgets as an overlay on the second monitor"
$sc.Save()
Write-Output "Startup shortcut: $lnk"

Start-Process -FilePath $overlayExe -WorkingDirectory (Split-Path $overlayExe)
Write-Output "Overlay started"
