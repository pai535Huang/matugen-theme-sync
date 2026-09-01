# Niri Managed Theme Integration Design

**Date:** 2026-09-01

## Goal

Make Niri support a complete, reversible Matugen integration rather than a set
of generated color fragments that applications do not load. The Niri mode will
deploy full themes for Waybar, Rofi, and Mako, connect the generated Niri color
fragment automatically, follow the wallpaper reported by awww or legacy swww,
and restore the user's original files when uninstalled.

The implementation must preserve the existing Plasma and GNOME behavior and
must not silently discard edits made before or after Niri integration is
installed.

## Chosen Approach

Use a managed theme package with a persistent original-state manifest.

Alternatives considered:

- Creating a timestamped full backup on every apply was rejected because it
  produces unbounded backups and makes the correct uninstall restore point
  ambiguous.
- Symlinking themes or changing application launch arguments was rejected
  because Waybar, Rofi, and Mako activate themes differently and users may
  start them through Niri, systemd, or another session manager.

The selected approach takes one durable snapshot when a path first becomes
managed, records the last deployed checksum, and uses a separate per-operation
snapshot for rollback. Repeated applies are idempotent. Uninstall has one
unambiguous original state to restore.

## Managed Resources

Static Niri desktop resources will live in a new repository directory:

```text
niri/
├── mako/config
├── rofi/matugen.rasi
└── waybar/style.css
```

Matugen continues to render only wallpaper-dependent colors:

| Component | Generated path | Static or patched integration |
| --- | --- | --- |
| Niri | `~/.config/niri/colors.kdl` | Managed include block in `config.kdl` |
| Waybar | `~/.config/waybar/colors.css` | Managed `style.css` |
| Rofi | `~/.config/rofi/colors.rasi` | Managed `themes/matugen.rasi` and theme block in `config.rasi` |
| Mako | `~/.config/mako/colors` | Managed complete `config` |

Waybar's module configuration is not managed. Rofi's existing configuration
options are preserved; only a marked theme-selection block is added. Niri's
other includes and settings are preserved. Mako is the exception because its
behavior and theme share one configuration file, so the complete file is
managed and restored as a unit.

## Persistent State and Backups

State is stored below
`${XDG_STATE_HOME:-~/.local/state}/matugen-theme-sync/niri/`:

```text
niri/
├── manifest.json
├── originals/
├── conflicts/<timestamp>/
└── transactions/
```

`manifest.json` records the logical target, resolved path, whether it existed,
its original mode, original backup location, and the checksum last deployed by
the project. It is written atomically. The first original snapshot is never
replaced by later applies.

Every apply also creates a short-lived transaction snapshot of the current
managed targets. A failed apply restores this snapshot, returning the system to
the state immediately before that invocation. A successful apply removes its
transaction directory.

Before overwriting a static managed file, apply compares it with the last
deployed checksum. A mismatch is treated as a user edit and copied to
`conflicts/<timestamp>/` before the project version is installed. Generated
color files are expected to change and are not treated as conflicts.

The Niri and Rofi main configurations use explicit managed blocks:

```text
// BEGIN MATUGEN THEME SYNC
include "./colors.kdl"
// END MATUGEN THEME SYNC
```

```text
/* BEGIN MATUGEN THEME SYNC */
@theme "matugen"
/* END MATUGEN THEME SYNC */
```

Apply replaces an existing well-formed block or appends one; it never creates a
second block. A partial or duplicated marker is an error and triggers rollback
rather than guessing how to edit the file.

On uninstall, well-formed managed blocks are removed from the current Niri and
Rofi configurations so unrelated edits made after installation survive. Static
managed files and the complete Mako configuration are restored from the
original snapshot. Paths that did not exist originally are removed. If a
static managed file differs from its last deployed checksum at uninstall time,
it is archived under `conflicts/` before restoration.

## Apply Transaction

Niri apply uses this order:

1. Resolve and validate repository resources and target paths.
2. Create the durable original snapshot if this is the first apply.
3. Create the per-operation rollback snapshot.
4. Install helper scripts, Matugen configuration, templates, service unit, and
   static Waybar, Rofi, and Mako resources. Do not start the watcher yet.
5. Run the forced initial Matugen generation to create all color files.
6. Add or update the Rofi and Niri managed blocks.
7. Validate the integrated configuration and reload the desktop components.
8. Enable and start `matugen-niri.service` only after the transaction succeeds.
9. Store deployed checksums and remove the transaction snapshot.

This removes the current race where systemd starts the watcher before the CLI's
initial generation finishes.

If any step fails, the operation disables any newly started service, restores
the per-operation snapshot, retains the durable original snapshot, and reports
the exact failing component. Project helper files may remain installed, but no
partially deployed application theme remains active.

`--no-bootstrap` installs the helper scripts, Matugen configuration, templates,
and service unit without beginning the managed-theme transaction. It does not
back up or replace application themes, add managed blocks, enable the service,
or reload applications. A later normal apply performs the complete transaction.
This prevents static Waybar or Mako configuration from referring to missing
generated colors and guarantees that `--no-bootstrap` cannot leave a partially
active theme.

## Theme Design

### Waybar

Use the user's current Material-style theme as the baseline. Retain its compact
height, module padding, workspace state hierarchy, tray behavior, and semantic
battery, network, audio, clock, media, and backlight colors. Remove the fixed
`/home/hjk` path and machine-specific comments. The deployed stylesheet will
load the resolved generated color path and add neutral fallbacks for common
modules, tooltips, and disabled states.

The stylesheet contains no fixed color values. Surface roles establish
elevation; primary and tertiary roles identify active or distinctive modules;
error roles are reserved for disconnected, urgent, and critical states.

### Rofi

Use the user's current rounded Material-style theme as the visual baseline.
Load `../colors.rasi` relative to `themes/matugen.rasi`, which Rofi resolves
relative to the importing file. Preserve the current input and list proportions
while defining the full widget tree that a standalone `@theme` discards:
message, mode switcher, row counters, placeholder, scrollbar, and text/icon
children.

Define normal, alternate, active, urgent, selected-normal, selected-active, and
selected-urgent states with readable background/foreground role pairs. The
theme contains no fixed color values or user-specific paths.

### Mako

The managed configuration retains the current placement, dimensions, grouping,
timeouts, do-not-disturb mode, and KDE Connect persistence behavior. Static
configuration contains no colors and includes the generated colors file using
a resolved path.

The generated colors cover the default notification, progress indicator,
low-urgency border, and critical notification. Criteria use Mako's supported
values `low`, `normal`, and `critical`; the current invalid `high` criterion is
removed. Background and text always use matching Material roles, such as
`surface_container_low` with `on_surface` and `error_container` with
`on_error_container`.

### Niri

The managed include is appended to the end of `config.kdl`. Niri includes are
positional, so this makes generated values override earlier static values.

The color fragment covers:

- a 135-degree `primary` to `tertiary` active focus gradient, plus inactive and
  urgent focus colors;
- border, shadow, tab indicator, and window insertion hint colors;
- overview backdrop and recent-window highlight colors; and
- the workspace background visible when no wallpaper layer is present.

The generated focus gradient is necessary because an earlier
`active-gradient` takes precedence over a later `active-color`; the current
local Niri layout already defines such a gradient. Options such as borders and
shadows remain controlled by the user's layout and only receive colors when
enabled.

## Wallpaper Detection and Runtime Watcher

The watcher queries the wallpaper daemon rather than watching an undocumented
cache directory:

1. Prefer `awww query --json` and parse the JSON without shell word splitting.
2. Fall back to legacy `swww query`, treating the entire value after the image
   marker as the path so spaces are preserved.
3. Fall back to an explicitly supplied image and then the existing wallpaper
   directories only for manual or startup generation.

When outputs display different images, sort case-insensitively by output name
and use the first valid image. Log the selected output and warn that the
resulting palette is global. Re-query periodically and invoke apply only when the selected image
identity changes. The watcher no longer monitors `~/.cache/awww` or regenerates
the palette for unrelated Niri configuration writes.

Niri detection prioritizes `NIRI_SOCKET` and explicit desktop-session hints.
The mere presence of an installed Niri, Plasma, or GNOME executable is not
enough to identify the active desktop when several are installed. Niri and one
wallpaper backend are operational requirements; Waybar, Rofi, and Mako remain
optional components and are reported as optional rather than missing required
dependencies.

## Validation and Tests

Template and resource tests verify:

- valid Matugen tokens and palette roles with no fixed hexadecimal colors;
- balanced and expected KDL, CSS, Rasi, and Mako structures;
- complete Rofi widget and state coverage;
- valid Mako urgency criteria and matching background/text roles;
- portable paths with no username or `/home/hjk` references; and
- all static resources are declared and deployable.

Temporary-HOME integration tests verify:

- first-apply backup and deployment;
- repeated-apply idempotency and preservation of the original snapshot;
- managed block insertion, replacement, and malformed-block rejection;
- conflict archival;
- per-invocation rollback after failures;
- uninstall restoration, removal of originally absent files, and preservation
  of unrelated post-install configuration edits; and
- `--no-bootstrap` behavior.

Watcher and detection tests use fake executables to cover awww JSON, paths with
spaces, deterministic multi-output selection, legacy swww output, wallpaper
fallbacks, Niri session precedence, and optional dependency reporting.

Final verification runs the complete Python unittest suite and `bash -n` on all
shell scripts. When the corresponding local tools exist, it also validates a
rendered integrated Niri configuration with `niri validate`, parses the Rofi
theme through dump mode, and starts Mako against an isolated invalid Wayland
display to distinguish configuration parse errors from display connection
errors.

## Documentation

README Niri instructions will describe the automatic managed integration,
backup location, conflict archive, multi-output wallpaper choice, optional
components, manual recovery, and uninstall restoration. The obsolete `import`
examples and claims about a `colors.*` Niri namespace will be removed.

Upstream references:

- [Niri include behavior](https://github.com/YaLTeR/niri/wiki/Configuration%3A-Include)
- [Niri layout colors](https://github.com/YaLTeR/niri/wiki/Configuration%3A-Layout)
- [Waybar Niri workspace states](https://github.com/Alexays/Waybar/blob/master/man/waybar-niri-workspaces.5.scd)
- [Mako configuration](https://github.com/emersion/mako/blob/master/doc/mako.5.scd)
- [Rofi theme file handling](https://davatorium.github.io/rofi/current/rofi-theme.5/)
