# Usability test: Sheaf 1.0 (November 2026)

## Method and its limits

This was an **expert review plus scripted task runs**, not a study with real users. No
participants were recruited, so it can't measure real-world task times, confusion or
satisfaction. Run a short moderated test with 3 to 5 people before calling the UX finished
(see "Next step" below).

What was done:

1. **Scripted task runs.** The six key flows from the PRD were driven end to end in the real
   window (off-screen) and the saved files checked: `tests/test_ui.py`. All pass.
2. **Screen review.** Every main screen was rendered with sample documents (`tools/screenshots.py`)
   at a common laptop size (1366x768), in a small window (1024x640), in light and dark themes, and at
   200% display scaling, then reviewed against Nielsen's 10 usability heuristics and the PRD's
   quality bar (Acrobat, PDF Expert and Foxit as the benchmark).
3. **Step counts** for each key flow, counted as clicks and key presses with no menus needed.

## Key flows

| Flow | Steps | Result |
| --- | --- | --- |
| Merge: drop files, reorder, save | Drop files, choose Combine, drag pages, Ctrl+S, name it | Pass |
| Fix a scan: rotate one page, delete another | Organize, hover page and click rotate, hover page and click delete, save | Pass |
| Fill and sign | Fill & Sign, Tab through fields while typing, Sign, click to place, save | Pass |
| Copy a passage | Drag across text, Ctrl+C | Pass |
| Add text | T, click, type, set font and color | Pass |
| Unlock a file | Open with password, Protect, Remove password, save | Pass |

## Findings

Severity: 3 = blocks or misleads users, 2 = slows them down, 1 = polish.

| # | Finding | Severity | Status |
| --- | --- | --- | --- |
| U1 | The "Fill & Sign" mode button showed "Fill  Sign": Qt read the "&" as a keyboard mnemonic | 3 | Fixed |
| U2 | Opening a file zoomed to fit width (140% on a laptop), so a form's fields started below the screen and Fill & Sign looked empty | 3 | Fixed: opening zooms to fit width up to 125%; Fill & Sign now says how many fields there are and Tab jumps to the first |
| U3 | Toolbar buttons showed long menu names ("Insert pages from file", "Rotate pages right") that crowd small windows | 2 | Fixed: short labels; the full name stays in the tooltip and menus |
| U4 | The comments list used PDF jargon ("FreeText", "Text", "Line") | 2 | Fixed: "Text box", "Note", "Arrow", and highlights quote the words they mark |
| U5 | Recent files showed long full paths with a horizontal scrollbar | 2 | Fixed: file name first, folder shortened, full path on hover |
| U6 | Zoom level was visible only in View mode | 2 | Fixed: zoom is always shown in the status bar, click to type a level |
| U7 | In Organize, pages from different files had colored edges with no key | 2 | Fixed: a legend names each file's color |
| U8 | Organize showed the "select text" hint in the status bar, which doesn't apply there | 1 | Fixed |
| U9 | Font size showed as "12.00 pt" | 1 | Fixed: "12.0 pt" |
| U10 | View mode had a lone "Select" tool button with nothing to switch to | 1 | Fixed: removed |
| U11 | Watermarks on rotated pages were diagonal but off-center | 2 | Fixed and checked on 0° and 90° pages |
| U12 | Tests and screenshot runs wrote recent-file entries to the real Windows registry | 2 (privacy) | Fixed: settings honor the test location; leftover entries removed |
| U13 | Highlight quotes in the comments list cut words at the edges | 1 | Fixed, with a test |

## Open issues (not fixed in 1.0)

| # | Issue | Severity | Suggestion |
| --- | --- | --- | --- |
| O1 | Links inside PDFs (including a table of contents) can't be clicked | 2 | Follow internal page links only; keep external links off for privacy, or ask first |
| O2 | A placed signature can be undone but not moved afterwards | 2 | Place signatures as stamp annotations so they can be dragged |
| O3 | Undo keeps a full copy of the document per step, so each edit on a very large file (100 MB and more) can take a second | 2 | Use MuPDF's built-in journal for undo |
| O4 | Only Helvetica, Times and Courier are offered for new text | 1 | Offer installed Windows fonts, embedded in the PDF |
| O5 | No thumbnails-only quick "reverse order" or "sort" for scanned stacks | 1 | Add to More tools |
| O6 | Text tools have no visible on-page hint the first time | 1 | One-time coach marks |

## Next step: a short test with people

Recruit 3 to 5 people who handle PDFs at home or work but don't use Acrobat daily. Give each the
six key flows with made-up documents, ask them to think aloud, and note where they hesitate.
Success: every flow done in under 60 seconds without help, and no one changes an original file
by accident.
