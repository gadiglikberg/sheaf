## Install on Windows

**[Download Sheaf-Setup.exe](https://github.com/gadiglikberg/sheaf/releases/latest/download/Sheaf-Setup.exe)** and run it. It installs for your Windows account only (no administrator password), adds Sheaf to the Start menu, and offers it under **Open with** for PDF files. Uninstall any time from **Settings → Apps**.

Prefer not to install? Download **Sheaf-windows.zip**, unzip it (right-click → Extract all) and run `Sheaf.exe`.

**"Windows protected your PC":** this release isn't code-signed yet, so Windows may warn you the first time. Click **More info → Run anyway**.

## Install on a Mac

**[Download Sheaf-mac.dmg](https://github.com/gadiglikberg/sheaf/releases/latest/download/Sheaf-mac.dmg)**, for Macs with Apple silicon (M1 or later) on macOS 14 Sonoma or later. Intel Macs aren't supported: the PDF engine Sheaf is built on no longer ships for them.

Open it and drag **Sheaf** onto **Applications**. Sheaf then appears under **Open With** for PDF files in Finder.

**"Apple could not verify Sheaf":** Sheaf isn't notarized by Apple (that needs a paid Apple developer account), so the first time you open it macOS refuses. Click **Done**, open **System Settings → Privacy & Security**, scroll down to "Sheaf was blocked" and click **Open Anyway**. You only need to do this once.

## Check your download

To confirm a file is exactly what was built here from the public source code, compare its SHA-256 with `SHA256SUMS.txt` below. Windows (PowerShell): `Get-FileHash .\Sheaf-Setup.exe`. Mac (Terminal): `shasum -a 256 ~/Downloads/Sheaf-mac.dmg`.

## Private by design

Sheaf has no network code: nothing you open or save is uploaded, and it works with the internet unplugged. Every release is built by GitHub Actions from the tagged source code, after the tests and the no-network check pass on Windows and macOS.
