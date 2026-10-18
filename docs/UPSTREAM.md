# Upstream synchronization policy

Upstream: https://github.com/GetLostIn/CTR-NitroFueled-PC, branch `main`.
Distribution: https://github.com/zamkara/CTR-NitroFueled, native Arch Linux x86_64.

`packaging/arch/sync-upstream.sh` fetches and merges the full upstream history before each main
workflow build. It restores this fork's `.github`, `packaging`, `README.md`, this document and
`tests/test_arch_packaging.py` from the original fork commit. Upstream source fixes are merged;
new upstream workflow files cannot activate Windows or AppImage publication in this fork.
README instructions and Arch release policy remain local. Legacy upstream packaging sources may
remain for reference and tests; they are not run by the native release workflow.

The merge aborts on unresolved source conflicts. There is no automatic ours/theirs resolution,
force-push or silent source overwrite. A bot merge made with GITHUB_TOKEN does not trigger a second
push workflow; subsequent jobs explicitly check out the synchronized commit in the current run.
Pull requests run validation/build/smoke but cannot synchronize the main branch or publish.

A release already published for the synchronized full commit skips rebuilding. Failed builds
remain retryable. Artifacts are uploaded to a temporary draft before publication so users never
receive a latest release missing its package or checksums. Final releases are not drafts or
prereleases. Required checks run before publication. Repository Actions must remain enabled;
GitHub may disable scheduled workflows in inactive public forks.

Known limits: the upstream GTK launcher differs from its Windows launcher. Runtime correctness
without a real game dump is limited to synthetic tests; no gameplay or GPU compatibility claim
is made by CI. Linux DLSS support is not promised by this packaging. Arch is rolling release:
builds use the Arch container repositories, which may be newer than pinned Omarchy snapshots.
