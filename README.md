# CTR Nitro-Fueled for Arch Linux

Native x86_64 Arch Linux packaging for Crash Team Racing: Nitro-Fueled, including Omarchy.
Based on [GetLostIn/CTR-NitroFueled-PC](https://github.com/GetLostIn/CTR-NitroFueled-PC),
which derives from [SacredFire](https://github.com/T3CHNOLOG1C/SacredFire), bbport and shadPS4.
This fork produces Arch packages; upstream remains responsible for its Windows distribution.

No game files are included. You need your own decrypted **CUSA13795** base game and **1.21 update**.
Other regions are not supported by upstream. Requires an x86_64 CPU with AVX and a Vulkan 1.3 GPU driver.

## Install or update

After the first successful build, use the same command for installation and upgrades:

```bash
curl -fsSL https://github.com/zamkara/CTR-NitroFueled/releases/latest/download/install.sh | bash
```

The script downloads without root, verifies the package against the release's SHA256SUMS,
compares versions, and invokes pacman only when needed. A checksum detects corruption; it is
not a signature independent of the GitHub account. Pacman prompts through the terminal even
when the installer is piped into bash. Dependencies come from your configured Arch repositories.
Keep the system updated before installing. Runtime libraries must match the Arch repositories
used to build the package; older pinned Omarchy snapshots may require a system update.

The application menu contains:

- **Launcher Crash Team Racing Nitro-Fueled** — select the prepared game folder and settings.
- **Crash Team Racing Nitro-Fueled** — launch directly using those same saved settings.

Terminal equivalents: `ctr-nitrofueled` and `ctr-nitrofueled --play`.
The lightweight launcher defaults to the GTK Cairo renderer; `GSK_RENDERER=gl` or
`GSK_RENDERER=vulkan` overrides it. This does not change the game's Vulkan renderer.
Without a prepared game folder, the direct-play shortcut opens the launcher for setup.
The Linux launcher is upstream's GTK4/libadwaita launcher; it does not promise feature parity
with upstream's newer Windows launcher. Headless build checks do not establish gameplay compatibility.

## Updates and controls

Open **Settings → Application updates → Check for Updates** to check the latest native package.
Checks run only on request and do not send local paths, settings or installed-version metadata.
When an update is available, **Install Update** opens the normal terminal installer. It verifies
the package checksum and lets pacman handle dependencies and authentication. Stop the game before
updating and restart the launcher afterward.

The **Controls** tab maps keyboard keys and controller buttons/triggers to the runtime's PS4 inputs.
Each action supports up to four bindings, searchable by SDL key/button name. Keyboard names refer
to physical key positions. Empty selections unbind an action. Keyboard and controller sections
have independent reset actions; analog sticks retain their native axes. Mappings are saved to
the same `bbport.ini` used by direct play and apply on the next game launch. Controller mapping
uses SDL button names rather than controller-specific branding.

## Prepare your game

Extract your own decrypted base game and update into separate folders. Merge the update using
upstream's hard-link tool; this does not alter the original game folders:

```bash
python /usr/lib/ctr-nitrofueled/tools/merge_update.py /path/to/base /path/to/update /path/to/merged
```

Select `/path/to/merged` in the launcher. The tool falls back to copying when hard links are
unavailable; allow enough disk space. See upstream's [dump requirements](https://github.com/GetLostIn/CTR-NitroFueled-PC#which-game-dumps-work).

Generated files, saves and caches live in `~/.local/share/ctr-nitrofueled`.
Launcher settings retain upstream's `~/.config/sacredfire-launcher/settings.json` location.
`BB_DATA_DIR`, `BB_USER_DIR`, `BB_CONFIG`, `XDG_DATA_HOME` and `XDG_CONFIG_HOME` overrides are supported.
Steam shortcuts created through this package point at the installed wrapper and use the same settings.

Remove with `sudo pacman -Rns ctr-nitrofueled`. User saves and settings are preserved.

## Build and release

The scheduled daily workflow, manual runs and pushes to `main` fetch and merge
upstream before building. Source history is preserved. This fork's packaging, workflows and README
are protected; source conflicts stop synchronization for review instead of discarding either side.
An already published source hash skips the build. Every published release uses `arch-<full commit>`
and contains the package, PKGBUILD, SRCINFO, installer and SHA256SUMS. Releases become public,
non-draft and non-prerelease only after the clean Arch smoke test passes.

Build manually with `makepkg -s` from `packaging/arch`. Set `CTR_COMMIT` to a published full source
commit. Build dependencies and renderer submodules are pinned to that source; the VMA header is
versioned and checksummed. Build and smoke jobs run in disposable Arch containers, not on the host.
Native C/runtime and Python tests run before packaging; the smoke test installs, opens the launcher
as an unprivileged user, checks shared libraries and removes the package while preserving user data.

See [upstream synchronization policy](docs/UPSTREAM.md).
