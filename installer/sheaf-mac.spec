# PyInstaller recipe for the Mac app (Sheaf.app). Used by the Release workflow on a macOS runner:
#   python -m PyInstaller --noconfirm installer/sheaf-mac.spec
# It expects build/Sheaf.icns, which the workflow makes with tools/make_icon.py --iconset and iconutil.
# PyInstaller signs the app "ad hoc" (no Apple certificate); see README for what that means for users.
import re
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "src" / "sheaf" / "__init__.py").read_text()).group(1)

a = Analysis([str(ROOT / "tools" / "launcher.py")], pathex=[str(ROOT / "src")])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Sheaf", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Sheaf")
app = BUNDLE(
    coll,
    name="Sheaf.app",
    icon=str(ROOT / "build" / "Sheaf.icns"),
    bundle_identifier="io.github.gadiglikberg.sheaf",
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": "Sheaf",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHumanReadableCopyright": "AGPL-3.0-or-later",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.productivity",
        # Offer Sheaf under "Open With" for PDFs without taking over the default PDF app.
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "PDF document",
            "CFBundleTypeRole": "Editor",
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["com.adobe.pdf"],
        }],
    },
)
