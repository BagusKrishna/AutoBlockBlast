# Branching workflow

This project uses two long-lived branches:

- **`main`** holds versions designated for stable release. It is the GitHub default branch.
- **`development`** holds ongoing changes, experiments, fixes, and documentation. It may contain work that is not yet release-ready. Do day-to-day work here.

## Daily work

```bash
git switch development
git pull --ff-only origin development
# Make and verify changes.
git add <files>
git commit -m "Describe the change"
git push origin development
```

Avoid committing directly to `main` for ordinary development. Keep commits focused and avoid including local captures, credentials, virtual environments, or scrcpy binaries.

## Promoting a release

When the user requests a release, verify the intended `development` commit, review the changes and known limitations, and run the relevant automated and device checks. Then propose a pull request from `development` into `main` for review and merge it only when the user authorizes the release. Tagging or publishing a release is a separate action to perform when requested. After the merge, keep development in sync with `main` before continuing.

These are workflow conventions, not GitHub-enforced branch protection rules. No additional feature or release branches are required by default.
