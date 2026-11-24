## Install

**[Download Sheaf-Setup.exe](https://github.com/gadiglikberg/sheaf/releases/latest/download/Sheaf-Setup.exe)** and run it. It installs for your Windows account only (no administrator password), adds Sheaf to the Start menu, and offers it under **Open with** for PDF files. Uninstall any time from **Settings → Apps**.

Prefer not to install? Download **Sheaf-windows.zip**, unzip it (right-click → Extract all) and run `Sheaf.exe`.

### "Windows protected your PC"

This release isn't code-signed yet, so Windows may warn you the first time. Click **More info → Run anyway**. To check that your download is exactly what was built here from the public source code, compare its SHA-256 (in PowerShell: `Get-FileHash .\Sheaf-Setup.exe`) with the value in `SHA256SUMS.txt` below.

## Private by design

Sheaf has no network code: nothing you open or save is uploaded, and it works with the internet unplugged. Every release is built by GitHub Actions from the tagged source code, after the tests and the no-network check pass.
