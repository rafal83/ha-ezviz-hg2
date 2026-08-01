# Publishing checklist

## Create the repository

1. Create the public repository `rafal83/ha-ezviz-hg2` on GitHub.
2. Push the contents of this directory to the default branch.
3. Set the repository description to `Home Assistant integration for EZVIZ HG2 gate controllers and CH3 chimes`.
4. Add the topics `home-assistant`, `hacs`, `ezviz`, `hg2`, `ch3`, and `gate`.
5. Enable Issues and private vulnerability reporting.

## Validate and release

1. Confirm the HACS and hassfest jobs pass without ignored checks.
2. Confirm installation works when the repository is added as a custom HACS integration.
3. Confirm `custom_components/ezviz_hg2/manifest.json` contains the intended version.
4. Create and push a matching tag, for example `v0.1.0` for manifest version `0.1.0`.
5. Let the release workflow create the full GitHub release.

## Propose it as a HACS default repository

1. Fork `https://github.com/hacs/default`.
2. Create a branch from `master`.
3. Add `rafal83/ha-ezviz-hg2` alphabetically to the `integration` file.
4. Open a pull request from the personal fork and complete every item in the HACS template.

HACS requires the public repository, successful HACS and hassfest actions, at least one GitHub release, an icon, a description, topics, and enabled issues before reviewing a default-repository submission.
