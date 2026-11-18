# Security policy

Sheaf opens PDFs from anywhere, so we take reports seriously.

## Reporting a vulnerability

Please **don't open a public issue**. Use GitHub's private reporting instead:
go to the repository's **Security** tab and choose **Report a vulnerability**.

Include what you did, what happened, and a PDF that shows the problem if you can. Only send
files that contain no personal data; a generated test file is best.

We aim to reply within 7 days and to ship a fix for confirmed issues as quickly as we can.

## Scope

In scope: anything that lets a PDF or image make Sheaf run code, read or write files the user
didn't choose, reach the network, leak redacted or password-protected content, or crash in a way
that loses the user's work.

Bugs in PyMuPDF/MuPDF or Qt should also be reported upstream; we'll help coordinate.

## Design notes

- No networking or process-launching code; enforced by `tools/check_no_network.py` in CI.
- PDF JavaScript is disabled and PDF links and launch actions are never followed.
- Saves always rewrite the whole file (never incremental), so removed content doesn't linger.
- See [docs/security-audit.md](docs/security-audit.md) for the full review.
