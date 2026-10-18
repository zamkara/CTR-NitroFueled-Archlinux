# Linux launcher features and validation

The GTK launcher and direct-play shortcut use the same settings and `bbport.ini`.
The Linux package remains independent of upstream's Windows distribution.

| Feature | Linux behavior |
| --- | --- |
| Game setup | Library → Prepare Game selects separate matching base/update dumps and creates a new merged view; original dumps are preserved. |
| Regional validation | CUSA13795 and the pinned CUSA14876 1.21 executable; unknown European builds are rejected. |
| Internal resolution | 480p, 720p, 1080p, 1440p, 1620p, 2160p; Linux now selects the corresponding rendering path and memory budget, as Windows does. Restart required. |
| Upscaling | Off, FSR 1, experimental FSR 3; sharpness controls are written to the runtime's own keys. |
| DLSS | Unavailable: the upstream NGX bridge implements Windows only. It is not offered by the GTK launcher and is disabled in the Linux in-game menu. No Linux DLSS quality/model support is claimed. |
| FPS limit | 30, 60, 72, 90, 120, 144, 240 and uncapped. Selecting more than 30 automatically enables the required unlock patch. Disabling that patch returns the launcher limit to 30. |
| Shader compilation | Optional experimental background compilation; effects can appear late. |
| Game window | Fullscreen/windowed, presentation mode and monitor selection. Saved in-game fullscreen changes are reloaded by the launcher and retained across Apply and restart. Windowed dimensions are independent of internal render resolution. |
| Controllers | Player 1–4 assignment and keyboard/gamepad mappings. Analog axes retain the native runtime behavior. |
| Saves | Per-player/per-region listing, backup, restore, export and decrypted PS4/runtime save import. Existing saves are backed up before replacement. |
| DLC | Import matching own packages, enable/disable individual entitlements, remove managed packages. Sources outside the managed DLC folder are never removed. |
| Patches | Bundled community switches plus additional matching XML patches from the data patches directory. Unique signature validation remains mandatory for relocated writes. |
| Statistics | Built-in FPS counter and MangoHud FPS, frame time, CPU/GPU, memory and resolution. FPS sampling: one or two seconds. |
| Diagnostics | Collapsed advanced options and the Log page, with export. |
| Updates | Manual native-package update check and the checksummed installer. |
| Steam | Existing integration launches the same saved configuration. |

## Important limits

An FPS limit is a ceiling, not a performance promise. Reaching 120+ FPS depends on
CPU/GPU load, drivers, resolution and the scene. The stock game remains 30 FPS
without the unlock patch. Patches apply on the next launch or Apply and restart.
The 60 FPS unlock does not guarantee 60 FPS, and high rates need gameplay testing.

FSR 3 is experimental temporal upscaling, not a promise of frame generation.
New options are wired to existing renderer behavior; every combination has not been
benchmarked on every GPU. The CUSA14876 title screen and main menu were observed
locally on an NVIDIA GTX 1650; complete races and long sessions remain unverified.

Runtime save imports accept a folder containing slot directories and matching
`<slot>.sce_sys/param.bin`. Decrypted PS4 saves need `sce_sys/param.sfo` with a
matching title and valid `SAVEDATA_DIRECTORY`; encrypted PS4 saves are not decrypted.
Exports and new backups include an edition marker. Legacy runtime backups without
that marker cannot independently prove their region: select the correct edition.
Symbolic links/special files are rejected. An existing save is backed up before
staging and publication; a publication error rolls back the active folder. This
is not a guarantee of crash/power-loss durability. SaveDataMemory files outside
the edition's save directory are not included, matching upstream's save-folder scope.

File operations require the game to be stopped. Another independently launched game
process can still write the same saves; stop that process as well. Keep a separate
backup before importing third-party data. Identical controller models can share an
SDL GUID, so individual physical-device assignment may remain ambiguous.

Network gameplay is unchanged: socket/HTTP/PSN services remain offline stubs.
Local split-screen does not imply online matchmaking support.

## Verification

Regression tests cover render-plan memory selection, automatic FPS patch activation,
fullscreen synchronization, restart/mod-view cleanup, DLC/patch GTK controls, matching
edition checks, source preservation, save metadata conversion, backup failure,
publication rollback, safe export and rejected symbolic links/path traversal.
The C++ settings check covers both fullscreen transitions and explicit windowed
startup overriding persisted fullscreen. CI now runs that target during packaging.

Local native runtime checks link the existing installed renderer; this is distinct
from a full renderer rebuild. Changed window and overlay sources receive separate
compile checks. The release workflow rebuilds the complete renderer and runtime,
runs the test suite, installs in a fresh Arch environment and opens the launcher
before publishing. No game files are uploaded to CI, so CI does not establish
hardware gameplay or DLC item compatibility.

### Local results for this change

```
Ran 152 tests in 9.155s
OK
PASS: settings save keeps other keys, menu position
PASS: pad ABI, debug camera chord, left/right clicks, SDL touch coordinates, overlay capture, controls, stick calibration
PASS: AppContent lifecycle, profile and output boundaries
PASS: AppContent add-ons
PASS: event flag contracts
```

The Python result above has no skipped tests. The native pad, runtime, file-mod,
semaphore, content and event-flag programs were built and executed locally using
the installed renderer. The settings test separately checked explicit windowed
startup, fullscreen startup and persistence back to windowed. Game-window/overlay
C++ compile checks and shell/Python syntax checks also passed. A live desktop
observation showed the CUSA14876 main menu and MangoHud statistics after selecting
the prepared folder; this was not a full gameplay benchmark or proof of 120 FPS.

Native game startup was also observed through Hyprland, with isolated test saves:

```
{"requested": "windowed", "fullscreen": 0, "fullscreenClient": 0, "size": [763, 1028]}
{"requested": "fullscreen", "fullscreen": 2, "fullscreenClient": 2, "size": [1920, 1080]}
PASS: native game windowed and fullscreen startup observed on Hyprland
```

The windowed size was assigned by the tiling compositor. This test used the newly
compiled runtime with the installed renderer. Live menu toggling was checked at
the settings/persistence layer, not by an automated mouse interaction with the game.
