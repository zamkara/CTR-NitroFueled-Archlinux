# CTR Nitro-Fueled for Arch Linux
<img width="1920" height="1080" alt="screenshot-2026-10-18_15-19-54" src="https://github.com/user-attachments/assets/53cfda66-6e41-4dfb-bf53-1a4664a8f601" />

Native x86_64 Arch Linux packaging for Crash Team Racing: Nitro-Fueled, including Omarchy.
Based on [GetLostIn/CTR-NitroFueled-PC](https://github.com/GetLostIn/CTR-NitroFueled-PC),
which derives from [SacredFire](https://github.com/T3CHNOLOG1C/SacredFire), bbport and shadPS4.
This fork produces Arch packages; upstream remains responsible for its Windows distribution.

No game files are included. You need your own decrypted base game and **1.21 update**.
This fork recognizes upstream CUSA13795 and the verified CUSA14876 1.21 executable.
CUSA14876 support is experimental; see [regional validation and limits](.github/workflows/ctr/docs/CUSA14876.md).
Other executable builds remain unvalidated. Requires an x86_64 CPU with AVX and a Vulkan 1.3 GPU driver.

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

The launcher's **Performance statistics** group enables a MangoHud overlay with FPS,
frame time, CPU/GPU utilization, video memory, RAM and resolution. FPS sampling can be
set to one or two seconds. MangoHud is installed with the native package. Existing
`MANGOHUD_CONFIG` settings and explicit environment overrides take precedence.
The lightweight built-in FPS counter remains a separate option; enabling both produces
two counters. Settings also apply to the direct-play shortcut.

The expanded launcher includes graphics, frame limits, monitor/window mode, per-player
controllers, save management, DLC and additional XML patches. Details and honest limits:
[Linux features and validation](.github/workflows/ctr/docs/FEATURES.md).

## Prepare your game

Extract your own decrypted base game and update into separate folders. Open **Library → Prepare Game**
and select both. You can also merge them with the hard-link tool; original dumps remain unchanged:

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

This is a thin native packaging repository. The root contains only this README,
LICENSE and .github. Build policy, documentation, regression tests and the reviewed
native feature patches live in [.github/workflows/ctr](.github/workflows/ctr).

Daily, manual and main-branch builds fetch a pinned upstream revision, apply the
native feature patch queue, build in a disposable Arch container, run native tests
and validate installation, launcher startup and removal before publication. Patch
conflicts stop the build for review. An unchanged complete release is skipped.
No Windows or AppImage releases are produced by this repository.

Release tags use a digest of the upstream and native policy commits. Both exact
revisions are recorded in the checksummed upstream.json asset. Published PKGBUILD
and SRCINFO pin their sources so packages can be reproduced independently.
Existing installer commands and updater clients remain compatible.

Developer commands and the source-update policy are documented in the
[build helpers](.github/workflows/ctr/README.md) and
[synchronization policy](.github/workflows/ctr/docs/UPSTREAM.md).
