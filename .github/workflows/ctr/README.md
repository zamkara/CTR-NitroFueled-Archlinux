# Native build policy

- arch/: pinned Arch recipe, installer, wrapper, desktop entries and container checks.
- patches/: reviewed changes on top of the upstream revision in upstream.json.
- docs/: Linux feature coverage, verification and synchronization policy.
- materialize.py: apply feature patches and inject the native build policy into a source checkout.
- prepare.py: resolve the upstream head, compute the build identity and check publication state.
- test_*.py: packaging and pipeline regression tests.

Root cleanup does not rewrite Git history. Existing native features are preserved
as a patch queue rather than a second vendored source tree.

## Work on source

```bash
git clone https://github.com/GetLostIn/CTR-NitroFueled-PC.git /path/to/ctr-source
git -C /path/to/ctr-source checkout <full-upstream-commit>
python .github/workflows/ctr/materialize.py --source /path/to/ctr-source
git -C /path/to/ctr-source submodule update --init --recursive
cd /path/to/ctr-source
bash build.sh --test
python -m unittest discover -s tests
```

Use a clean disposable source checkout: materialization intentionally refuses local
changes. Patch conflicts fail closed. Update the reviewed patch queue when upstream
changes overlap native features, and run the same native tests before publishing.

Build manually with makepkg -s in arch/. CTR_COMMIT and CTR_UPSTREAM can select full
immutable commits. Published recipes replace both defaults with literal release pins.
Build artifacts belong in .github/workflows/.build or outside this checkout.

## Cleanup verification

All 28 custom source files reconstructed from the pinned upstream revision and the
native patch were compared byte for byte with the pre-cleanup feature checkpoint.
The final reconstructed application passed 151 tests without skips. The packaging
checkout has its own pipeline/layout checks; two application-only packaging tests
are intentionally deferred there and run in the materialized application's suite.
The source screenshot in README.md is retained. Original Git history is preserved;
this cleanup reduces the working tree, not the historical Git object database.

Physical keyboard bindings can be recorded directly with Record in the GTK dialog.
Escape cancels recording. Bindings remain individual physical keys, not GNOME-style
modifier chords: the runtime's comma-separated list means alternative inputs.
