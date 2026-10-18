# Source and update policy

This is a thin native Arch packaging repository. The root contains README.md,
LICENSE and .github. Build policy, tests, documentation and the reviewed native
feature patch queue live in .github/workflows/ctr. Upstream source is not vendored.

Each daily, manual or push build resolves GetLostIn/CTR-NitroFueled-PC main to a
full commit. The published PKGBUILD pins both that upstream revision and this
repository's policy revision. makepkg fetches both from their original repositories,
and materialize.py applies the native patches with Git's three-way conflict checks.
A conflict aborts the build for review; no feature patch is discarded automatically.
Upstream workflow/packaging changes never change this repository's release policy.

The release identity is the first 40 hexadecimal characters of SHA-256 over the two
full revisions, each followed by a newline. The arch-<digest> tag remains compatible
with existing native updater clients. Published upstream.json records both revisions
and is included in SHA256SUMS. An unchanged complete public release is skipped;
incomplete releases and failed builds remain retryable. Source history is retained
in Git, and this cleanup does not rewrite history or force-push.

Package versions use 0.r<policy commit count>.u<upstream commit count>.g<digest prefix>.
Both sources retain full history in makepkg so counts remain reproducible. The policy
count orders packaging changes; the upstream count orders daily updates. Normal
fast-forward source development is assumed. An intentional upstream rollback needs
a policy commit, which advances the first count and keeps pacman upgrades monotonic.

For development, materialize a separate source checkout; do not copy the upstream
tree into this repository. See the helper README for commands. A materialized source
contains the native launcher and all native regression tests as well as upstream
sources, modules, license notices and synthetic tests. No game data is fetched.

Build, full native tests and a clean Arch install/launcher/uninstall smoke test run
before publication. Temporary drafts are used only for atomic asset upload; completed
releases are public, non-draft and non-prerelease. The installer verifies checksums
and uses pacman for package transactions. User game files, saves and settings are
preserved on package removal.
