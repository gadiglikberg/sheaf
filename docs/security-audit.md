# Security audit: Sheaf 1.0 (November 2026)

## Summary

Sheaf's biggest risk is the one every PDF reader has: it parses files from strangers with a large
C library (MuPDF). Sheaf can't remove that risk, but it limits what a hostile file can reach:
there's no network code, no PDF JavaScript, no link or launch handling, and no shell or process
calls. The review found **no high-severity issues in Sheaf's own code**. Seven issues were fixed
and are now covered by tests; six are documented below with recommendations.

This was a code review plus automated scans by the developer (Claude). It is not an independent
penetration test. An outside review and fuzzing are recommended before wide promotion.

## Method

| Check | Tool | Result |
| --- | --- | --- |
| Static analysis of all source (3,950 lines) | Bandit 1.x | 0 high, 0 medium, 2 low (intentional catch-and-continue while rendering) |
| Known vulnerabilities in dependencies | pip-audit | None found (PyMuPDF 2.1 / MuPDF 1.28.6, PySide6 6.12) |
| No network or process-launching code | `tools/check_no_network.py` | Clean; runs in CI on every pull request |
| PDF JavaScript engine | Runtime check (`pdf_js_supported`) | Disabled in this build; test fails if that ever changes |
| Manual review | Threat model below | See findings |

## Threat model

- **Hostile PDF or image** opened, inserted or dropped by the user: tries to run code, reach the
  network, read or write other files, or exhaust memory.
- **Leaked content**: redacted text, password-protected content, or signatures ending up somewhere
  the user didn't intend (saved file, recovery copy, settings, clipboard).
- **Supply chain**: a compromised or vulnerable dependency or build pipeline.

## Fixed during the audit

| # | Issue | Severity | Fix |
| --- | --- | --- | --- |
| S1 | Redaction removed visible content but left hidden data: document properties, XMP metadata, bookmarks that repeat redacted words, attachments, scripts, thumbnails | High (for redaction users) | "Apply redactions" now removes hidden data by default (a checked box the user can clear). Test confirms author, bookmarks and attachments are gone from the saved bytes |
| S2 | A PDF declaring enormous pages could make the viewer allocate a huge bitmap at high zoom (crash or memory exhaustion) | Medium | Page bitmaps are capped at 60 megapixels; thumbnails guard zero-size pages |
| S3 | "Remove password" on a file with only author restrictions (no open password) removed them silently | Low (policy) | Sheaf now asks the user to confirm they have the right to remove restrictions. Restrictions are otherwise kept on save |
| S4 | An unused `QDesktopServices` import (can open URLs and files) | Low | Removed; the network check now bans it |
| S5 | Tests wrote recent-file paths into the real Windows registry | Low (privacy) | Settings follow the configured location; leftovers deleted |
| S6 | Editing existing text runs a redaction internally, which would also apply any areas the user had marked for redaction but not yet applied | Medium (data loss) | Pending marks are set aside and restored. Test covers it |
| S7 | Text typed into text boxes is stored as rich text (HTML); unescaped input could inject markup | Low | All user text is HTML-escaped. Test with a `<script>` payload |

## Verified properties (tests in `tests/test_security.py` and `tests/test_core.py`)

- No network, subprocess, `os.system`, `startfile`, web browser or Qt network imports anywhere in `src/`.
- PDF JavaScript is unsupported in the bundled MuPDF.
- No code path follows PDF links, URI actions or launch actions, or extracts attachments.
- Saves are full rewrites with garbage collection, never incremental, so removed or redacted
  objects don't survive in the file (exactly one `%%EOF`).
- Originals are read into memory and never modified; Ctrl+S on an opened file always asks for a new
  name; overwriting the original needs an explicit second confirmation.
- Writes are atomic (temporary file in the same folder, then rename).
- Password-protected documents stay AES-256 encrypted on save, in extracted pages and in recovery
  copies; the password never appears in the saved bytes or recovery metadata.
- Export file names are sanitized (no path traversal from a document name).
- A failed edit rolls the document back to its previous state.

## Open recommendations

| # | Recommendation | Severity | Why |
| --- | --- | --- | --- |
| R1 | **Keep PyMuPDF current.** Dependabot is configured; ship a release whenever MuPDF fixes a security bug | High | MuPDF parses untrusted input in C; its bugs are Sheaf's biggest exposure |
| R2 | **Fuzz the open, render and save paths** with a corpus of malformed PDFs (for example from the PDF.js and pdfium test suites) | Medium | Finds crashes before attackers do |
| R3 | **Sign the Windows build** (for example through a free code-signing program for open-source projects) | Medium | Unsigned downloads trigger SmartScreen and can't be verified |
| R4 | **Pin build dependencies with hashes** for releases and pin GitHub Actions to commit SHAs | Medium | Protects the release pipeline from a compromised package or action |
| R5 | Recovery copies of documents without a password are stored unencrypted in `%LOCALAPPDATA%\Sheaf\recovery` until saved or closed; signatures are stored as PNG files in `%LOCALAPPDATA%\Sheaf\signatures` | Low | Anyone with access to the Windows account can read them. Consider Windows DPAPI encryption |
| R6 | Passwords are held in memory as Python strings and can't be wiped; copied text goes to the Windows clipboard (and to Clipboard history or cloud sync if the user turned those on) | Low | Inherent to the platform; mention in docs |

Also noted: Sheaf ignores a PDF's "no editing" permission flags while editing (like most open-source
tools); the flags are preserved when saving.

## How to repeat this audit

```bash
python tools/check_no_network.py
python -m bandit -q -r src
python -m pip_audit --skip-editable
python -m pytest -q tests/test_security.py
```
