# Contributing to Sheaf

Thanks for helping! Sheaf aims to stay small, fast, private and easy to use.

## Ground rules

- **Privacy first.** No networking, telemetry, update checks or cloud features. CI rejects any import
  that could reach the network or launch programs.
- **Never commit real documents.** Tests generate their PDFs in code (see `tests/conftest.py`).
  When reporting a bug, don't attach PDFs that contain personal data.
- **Plain language** in the interface: say what a button does, avoid PDF jargon.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m pytest
```

UI tests run off-screen. `python tools/screenshots.py out` renders every main screen with sample
documents, which helps when reviewing UI changes.

## Pull requests

- Keep each pull request focused on one change and include tests.
- Run `python -m pytest`, `python tools/check_no_network.py` and `python -m bandit -r src` before pushing.
- By contributing you agree that your work is licensed under the AGPL-3.0, like the rest of Sheaf.

Please follow the [code of conduct](CODE_OF_CONDUCT.md).
