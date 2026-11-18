# Releasing Kaleido

Follow the steps in this document to release a new version of Kaleido.

## Overview

- Versions are determined automatically from git tags by `setuptools-git-versioning`. There is no hard-coded version string to update. Pushing a `v*` tag starts the `test-and-build` workflow, which builds and tests the package on each platform. That workflow publishes nothing.
- The `publish-pypi` workflow uploads the package to PyPI with trusted publishing (OIDC). A maintainer starts the workflow by hand, so no API token is necessary.
- Creating a GitHub release is done manually.

## Release steps

1. Create release branch titled `release-vX.Y.Z`
    - We try to follow [semantic versioning guidelines](https://semver.org) as much as possible
2. Update the changelog:
    - Review the items in `CHANGELOG.md` under the "Unreleased" header
    - Ensure all items follow this format:
        - `- Description of change [[#XXXX](https://github.com/plotly/Kaleido/pull/XXXX)]`
        - ...followed by `with thanks to @username for the contribution!` if the PR is from a community contributor
    - Add any missing items (PRs which were merged since the last release)
    - PRs which don't change the contents of the built package (e.g. changes to the README, etc.) and minor dependency upgrades don't need to be mentioned
    - Add a header `## vX.Y.Z` above the unreleased items, under `## Unreleased`
    - Commit and push the `CHANGELOG.md` updates
    - _Normally, the changelog is the only file that needs to be updated when making a release. The package version is determined automatically as explained in the overview above._
3. Open a PR into `main`, wait for tests to pass, get approval, and then merge into `main`.
4. On your local machine, check out `main`, pull, and tag the release branch merge commit with the version number:
    ```
    git checkout main
    git pull
    git tag vX.Y.Z
    git push origin vX.Y.Z
    ```
5. Watch the `test-and-build` workflow:
    - The tag push starts `.github/workflows/test_and_build.yml`
    - The workflow builds the package on Linux, Windows, and macOS for each supported Python version, then runs the tests against the built wheel
    - If the workflow fails, read the failure before you continue. A flaky browser test does not block the release, but a build failure does.
6. Release on PyPI:
    - Open the Actions tab and select `publish-pypi`
    - Select "Run workflow", enter the tag (for example `vX.Y.Z`), and start the run
    - Open the run and approve the deployment under "Review deployments"
    - The `pypi` environment needs a review from the `plotly/libraries_admin` team. The job waits for that approval before GitHub issues the OIDC token, so an unapproved run never reaches PyPI.
    - The workflow checks out the tag, builds the package, and confirms that the built version matches the tag. The upload uses `skip-existing`, so a second run of the same tag skips the files that PyPI holds already.
7. Release on GitHub:
    - Go to https://github.com/plotly/Kaleido/releases and click "Draft a new release"
    - Select the `vX.Y.Z` tag you created previously
    - Copy and paste the relevant changelog section into the release notes

That's it! Make sure to visit https://pypi.org/project/kaleido to verify that the new package version is available.
