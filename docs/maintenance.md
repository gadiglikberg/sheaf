# Keeping Sheaf maintained

Most upkeep runs by itself. This page lists what is automatic and the few things a person does.

## Automatic

| What | How |
| --- | --- |
| Security alerts | Dependabot alerts are on. GitHub emails the maintainer when a library Sheaf uses has a known vulnerability, and Dependabot opens a pull request with the fix. |
| Library updates | `requirements.txt` pins the exact versions that the tests and release builds use. Dependabot proposes new versions weekly as pull requests, once a version has been out for 7 days. Security fixes are proposed straight away. |
| Testing every update | Each pull request runs the tests, the no-network check, the static security scan and the vulnerability check on Windows (`test`) and macOS (`test-mac`). `main` only accepts changes that pass both. |
| Merging minor updates | Minor and patch updates from Dependabot merge by themselves once both checks pass. Major updates (for example PySide6 7) wait for a person. |
| Weekly health check | CI runs every Monday even without changes. A failure (for example a newly reported vulnerability) is emailed. |

Merging never publishes anything. Users only get changes when a release is published.

## Manual

**Publish a release** after updates have merged, or at least when a security alert has been fixed:
GitHub → **Actions → Release → Run workflow**, branch `main`, tick **Publish**, then **Run workflow**. The version
goes up by one patch step (1.1.0 → 1.1.1), Windows and Mac builds are made and tested, and the release appears on
the Releases page about 10 minutes later. This works from the GitHub mobile app too.

For a larger release, set the version in `src/sheaf/__init__.py` and `pyproject.toml` through a pull request,
then run the same workflow, or push a matching tag such as `v1.2.0`.

**Look at a major update** when Dependabot opens one: if its checks pass, merge it; if not, it needs code changes.

**Read failure emails**: a failed weekly run or a failed Dependabot pull request.

## Notifications

To get these emails, set the repository to **Watch → Custom → Releases, Security alerts** on GitHub, and keep
email notifications on in GitHub's notification settings.
