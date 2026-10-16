# Matugen Theme Sync

Generate wallpaper-derived light/dark themes with [matugen](https://github.com/InioX/matugen) and keep them synchronized across your desktop. Auto-detects **KDE Plasma**, **GNOME** or **Niri** and deploys the matching config, helper scripts, and systemd user service with one command — or one GUI click.

## Features

- One command / GUI to install, apply, or remove the whole theming pipeline for your current desktop
- KDE Plasma: wallpaper + selected `MatugenLight`/`MatugenDark` color scheme drive global light/dark sync
- GNOME: follows `org.gnome.desktop.interface color-scheme`; GTK, GNOME Shell, and apps refresh on change
- Niri: follows the running `awww`/`swww` wallpaper daemon and generates a managed dark theme for Niri, Waybar, Rofi, and Mako
- Themes GTK 3/4, GNOME color preference, Kitty, Neovim, btop, tmux, Zellij, Cava, Starship, Yazi, qt5ct/qt6ct
- Writes a pywal-compatible scheme to `~/.cache/wal/colors.json` so pywal/pywalfox software follows along

## Requirements

- `matugen`, `python3`, `flock`, `curl`
- KDE Plasma: `kreadconfig6`, `kwriteconfig6`, `plasma-apply-colorscheme`, `inotify-tools`
- GNOME: `gsettings`
- Niri: `niri`, either `awww` or legacy `swww`, and optionally `makoctl`, `waybar`, `rofi`
- GUI: `python-gobject`, `gtk4`, `libadwaita`

The Python side runs on the distribution interpreter on purpose, not in a
virtualenv: beyond the standard library the only imports are `gi`, its
`Gtk-4.0`/`Adw-1` typelibs, and the project's own `niri_integration`. PyGObject
publishes sdist-only on PyPI, so a venv copy compiles against the system GLib
and still reads the distribution's typelibs — the venv buys nothing and adds a
build step plus an ABI pairing to maintain. Install `python-gobject` (and
`gtk4` plus `libadwaita` for `show-ui`) with your package manager.

The installer checks for `matugen` before writing any project files. If it is
missing, it asks for confirmation with a safe `[y/N]` default, detects the
available package manager, and uses the matching flow:

| Distribution family | Automatic install |
| --- | --- |
| Arch | `pacman -S --needed --noconfirm matugen` |
| Fedora | `dnf -y install matugen` |
| Debian / Ubuntu | `apt-get` installs Cargo, then `cargo install --root ~/.local matugen` |

The Debian fallback builds Matugen with Cargo and places it in
`~/.local/bin`. Make sure that directory is in your `PATH`. Other
desktop-specific and GUI dependencies remain non-blocking and must be
installed with your distribution package manager when needed.

## Install

```bash
# from a checkout:
./install.sh

# or straight from GitHub:
curl -fsSL https://raw.githubusercontent.com/pai535Huang/matugen-theme-sync/main/install.sh | bash
```

Installs to `~/.local/share/matugen-theme-sync/`, links the `matugen-theme-sync` command into `~/.local/bin/`, and adds an app-menu entry.

Uninstall everything with:

```bash
~/.local/share/matugen-theme-sync/install.sh uninstall
```

## Usage

The desktop environment is detected automatically from your session.

```bash
matugen-theme-sync status      # show detected desktop + install state
matugen-theme-sync apply       # deploy config, scripts, and service; generate the theme
matugen-theme-sync uninstall   # stop the service and remove what apply deployed
matugen-theme-sync show-ui     # open the libadwaita GUI
```

Options: `--de plasma|gnome|niri` forces a desktop, and `--no-bootstrap`
applies support files without generating a theme. `--purge` is only available
on `uninstall`; its Niri behavior is described below.

### Per-desktop service binding

Each watcher is a companion of its desktop's own lifecycle unit, so it only
starts inside that desktop's session — convenient for machines with several
desktops installed:

| Service | Parent unit | Enable link |
| --- | --- | --- |
| `matugen-niri.service` | `niri.service` | `~/.config/systemd/user/niri.service.wants/` |
| `matugen-plasma.service` | `plasma-workspace.target` | `~/.config/systemd/user/plasma-workspace.target.wants/` |
| `matugen-gnome.service` | `gnome-session.target` | `~/.config/systemd/user/gnome-session.target.wants/` |

The parent unit starts the watcher when the desktop session starts and stops
it when the session ends (the same `PartOf` pattern used for swayidle under
Niri). Because the parent is often a system unit that user `systemctl enable`
cannot write into, the installer creates the enable symlink directly under
`~/.config/systemd/user/`, and `apply`/`uninstall` remove it again (also
cleaning up any leftover `graphical-session.target.wants` link from older
versions).

### KDE Plasma mode

The colour scheme selected in System Settings (`MatugenLight` or
`MatugenDark`) is the source of truth. The watcher reacts to `kdeglobals` and
to wallpaper changes and re-applies every managed application from the same
palette; a non-Matugen scheme disables synchronization.

The watcher forces a refresh when Plasma starts, restoring application themes
that another desktop may have overwritten. An explicit `apply --de plasma`
restores the last successful Matugen light/dark mode when the selected scheme
belongs to another theme. Remote wallpaper images are cached by URL so returning
to Plasma or switching modes does not require downloading the same image again.

#### Managed application themes

- GTK 3 and GTK 4 receive generated `~/.config/gtk-3.0/{gtk.css,colors.css}`
  and `~/.config/gtk-4.0/{gtk.css,colors.css}`. Plasma's GTK applications do
  **not** read dconf, so the light/dark choice is also written where they
  actually look: `gtk-theme-name` and `gtk-application-prefer-dark-theme` in
  `~/.config/gtk-3.0/settings.ini` and `~/.config/gtk-4.0/settings.ini`
  (`adw-gtk3` for light, `adw-gtk3-dark` for dark), and `Net/ThemeName` plus
  `Gtk/ApplicationPreferDarkTheme` in `~/.config/xsettingsd/xsettingsd.conf`
  when that file exists — followed by a `SIGHUP` to a running `xsettingsd`.
  Every other line of those files is preserved. The
  `org.gnome.desktop.interface` GSettings keys are still written for the
  settings portal and other consumers. Without the `settings.ini` step, GTK
  applications — Google Chrome's GTK theme mode included — keep the previous
  variant whatever colour scheme is selected, because no KDE GTK bridge
  (`kcm_gtk`, `kded` GTK/XSettings modules) is installed.
- Kitty receives the generated `~/.config/kitty/themes/Matugen.conf`, which is
  copied over `~/.config/kitty/current-theme.conf` and applied with `SIGUSR1`.
  The copy is deliberate: `kitten themes` loads its theme database from the
  network before writing anything, so a stale cache plus an unavailable
  network makes it exit without touching the file — which used to turn theme
  switches into silent no-ops. A `kitty.conf` without
  `include current-theme.conf` is reported, and a failed reload is reported
  instead of being swallowed.
- Neovim, btop and cava are signalled (`SIGUSR1`/`SIGUSR2`), tmux is reloaded
  when a server is running, and Starship follows the new colours.
  Zellij, Yazi, Obsidian, qt5ct/qt6ct and a new shell pick their files up on
  their next launch.
- Starship needs two things from `~/.config/starship.toml`, and gets both: the
  generated palette is copied into the `# BEGIN MATUGEN PALETTE` …
  `# END MATUGEN PALETTE` block, and the top-level `palette = "matugen"` key is
  set so Starship actually selects it — rewriting the block alone left the
  previous palette (for example a Noctalia block written by another tool) in
  charge. That key has to sit before the first table header, so it is written
  in the file's key section rather than next to the managed block. The palette
  carries both the positional `color0`…`color9` roles and the names Starship's
  default styles reference (`cyan`, `purple`, `red`, `green`, …), mapped onto
  Material roles: without the latter the prompt falls back to the terminal's
  own ANSI colours. A `starship.toml` without the marker comment pair is left
  untouched, since the block has nothing to rewrite.
- Qt colours are not regenerated in Plasma mode: the `qt5ct`/`qt6ct` templates
  are disabled in `matugen/config-plasma.toml`, so Qt applications keep the
  palette from whenever those files were last written.

### Pywalfox palettes and mode

Pywalfox derives both interface modes from a palette whose `color0` is dark
and `color7`/`color15` are light. Passing a conventional light terminal palette
reverses its foreground/background mapping. The light input template therefore
uses Matugen's light-mode `on_surface` for the dark base and `surface` for the
light text slots; accent colors still follow the selected Matugen mode. The dark
input template uses the selected mode's normal surface/text roles. Both use
`colors.*.default` and current color names, avoiding empty colors with Matugen 4.
This shared `~/.cache/wal/colors.json` follows Pywalfox's input convention even
when the desktop is light; consumers expecting a light terminal palette should
use a separate output.

Plasma's apply script sets the Pywalfox mode and requests a refresh after
successful generation. GNOME and Niri use bounded template hooks for the same
mode-then-refresh sequence; Niri generates dark mode. Pywalfox is optional.
Disable other theme generators' Pywalfox integration (for example Noctalia's)
to prevent them from overwriting the shared palette.

#### Optional Thunderbird compatibility fixes

These are manual, application-specific workarounds, not installed by this
project. In an affected Thunderbird 157.0.1 installation, the theme loader sets
`--lwt-accent-color`, while toolbar/status-bar CSS reads `--lwt-frame`. Enabling
Pywalfox can consequently expose a transparent window background. Separately,
Pywalfox 2.0.11 maps highlighted text to its dark focus text in light mode;
Thunderbird reuses that pair for primary buttons and the active spaces icon.

If affected, merge the relevant rules into the active Thunderbird profile's
`chrome/userChrome.css` and enable
`toolkit.legacyUserProfileCustomizations.stylesheets` in Thunderbird's config
editor. Restart Thunderbird after editing:

```css
/* Only needed when the theme loader and UI use different frame variables. */
:root[lwtheme] {
  --lwt-frame: var(--lwt-accent-color);
}

/* For Matugen's dark light-mode accents and light dark-mode accents. */
:root[lwtheme] {
  --sidebar-highlight-text-color: light-dark(#ffffff, #111416) !important;
}
```

The contrast rule assumes the default Pywalfox accent mapping used here;
custom palettes may need different foreground colors. Reassess these rules
after Thunderbird/Pywalfox updates and remove each workaround once unnecessary.

### Niri mode

Niri has no compositor-wide wallpaper or light/dark switch, so this mode always
generates Matugen in `dark` mode. It discovers the current image from the
wallpaper daemon with `awww query --all --json` first, reading all namespaces
and their multi-output entries. Valid displayed images are sorted by the
casefolded output name and then by image path; the first valid image supplies
the one global palette. Legacy `awww query` and `swww query` text output are
tried next.
Normal startup/manual generation may fall back to the first image under
`~/Pictures/Wallpapers` or `~/Pictures`; the watcher uses daemon results only.

Ordinary wallpaper paths containing spaces are preserved as one argument. The
shell text interface does not guarantee filenames containing a newline.

#### Managed application themes

A normal `matugen-theme-sync apply --de niri` performs the integration
automatically:

- Niri receives a marked block at the end of `~/.config/niri/config.kdl` with
  `include "./colors.kdl"`. Because Niri includes are positional, the generated
  fragment overrides earlier layout background, focus-ring, border, shadow,
  tab-indicator, and insert-hint colors, plus the overview backdrop and
  recent-window highlight colors.
- Waybar receives a complete managed `~/.config/waybar/style.css` that loads
  generated `colors.css`. Its module configuration is left untouched. On each
  theme change Waybar is restarted, because its GTK menus and tooltips are
  initialized once at process start and only a full restart makes them pick up
  the regenerated GTK colors.
- Rofi receives the complete `themes/matugen.rasi` theme and a marked
  `@theme "matugen"` block in `config.rasi`; unrelated Rofi settings remain.
- Mako receives a complete managed `~/.config/mako/config` that includes the
  generated colors file.
- GTK 3 and GTK 4 receive managed `~/.config/gtk-3.0/{gtk.css,colors.css}` and
  `~/.config/gtk-4.0/{gtk.css,colors.css}`. The import files are static
  (`@import 'colors.css';`), while the color files are generated by Matugen
  from the same palette. After generation the tool re-selects the GTK theme
  through gsettings (`color-scheme` → `prefer-dark`, `gtk-theme` →
  `adw-gtk3-dark`) so running GTK apps notice the regenerated colors, the same
  way the KDE watcher refreshes GTK.
- Qt 5 and Qt 6 receive generated `~/.config/qt5ct/colors/matugen.conf` and
  `~/.config/qt6ct/colors/matugen.conf` (the qtct approach used by the GNOME
  watcher). Qt apps pick the palette up on their next launch.

Waybar, Rofi, Mako, GTK, and Qt are optional. Missing optional applications are
reported but do not prevent Niri theming; installed applications are reloaded
when possible, while Rofi and Qt read their theme on their next launch. The
watcher continues polling the daemon and checks the selected image contents,
template/config hashes, and required generated files on every poll. Unchanged
themes skip regeneration; replacing an image at the same path or deleting a
generated file triggers regeneration.

#### Backups, transactions, and recovery

On the first managed apply, the tool records every target's original state in
`~/.local/state/matugen-theme-sync/niri` (or the corresponding
`$XDG_STATE_HOME` path). `manifest.json` identifies the targets and last
deployed checksums; backups under `originals/` are immutable and are not
replaced by later applies. Each apply also uses a short-lived snapshot under
`transactions/`, so a failed deployment, generation, validation, or service
setup rolls the whole application-theme change back to its pre-apply state.

If a managed static file was edited or removed after deployment, that divergence
is recorded under timestamped `conflicts/` (a deletion uses an `.absent`
marker) before replacement or restoration.
`matugen-theme-sync uninstall --de niri` disables the watcher,
removes the managed Niri/Rofi blocks while preserving unrelated edits, restores
the original Waybar/Rofi/Mako files, and removes files that were originally
absent. The original snapshot therefore remains the stable restore point for
the whole managed lifecycle. The snapshot covers every Matugen output,
including shared Kitty, Neovim, Yazi, and Pywalfox files, as well as Starship
and Kitty configurations rewritten by reload helpers and the synchronization
cache keys. Starship configurations without a complete managed palette block
are left unchanged.

Older manifests and interrupted transactions remain recoverable. Targets that
older versions did not track are first backed up on the next managed apply;
their pre-upgrade originals cannot be reconstructed retroactively.

`matugen-theme-sync uninstall --de niri --purge` additionally deletes
`~/.config/matugen` and `~/.cache/matugen-niri`. If `conflicts/` is empty, the
Niri state root is removed too. A non-empty `conflicts/` archive keeps the state
root and its archived edits, and uninstall prints the preserved archive path.

For a support-files-only setup pass,
`matugen-theme-sync apply --de niri --no-bootstrap` installs only the helper
scripts, Matugen config/templates, and service unit. It does not create a new
backup or transaction. It does not change the current application theme or watcher state.
On a clean first install this is zero theme takeover; after an
earlier managed apply it deliberately leaves the existing managed theme and
watcher state in place rather than undoing them. Use `uninstall --de niri` to
restore the originals and disable the watcher.

Recovery commands:

```bash
# Inspect recorded originals and deployed checksums.
less ~/.local/state/matugen-theme-sync/niri/manifest.json

# Inspect edits archived before replacement or restoration.
find ~/.local/state/matugen-theme-sync/niri/conflicts -type f -print

# Disable the watcher and restore the immutable first-apply originals.
matugen-theme-sync uninstall --de niri
```

## Layout

- `bin/` — CLI + GUI and per-desktop apply/watch helpers
- `matugen/` — matugen configs and shared templates
- `systemd/` — user service units
- `install.sh` — installer / uninstaller
