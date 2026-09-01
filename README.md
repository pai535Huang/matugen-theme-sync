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

Options: `--de plasma|gnome|niri` to force a desktop, `--no-bootstrap` to apply without generating a theme, `--purge` to also remove `~/.config/matugen`.

### Niri mode

Niri has no compositor-wide wallpaper or light/dark switch, so this mode always
generates Matugen in `dark` mode. It discovers the current image from the
wallpaper daemon: JSON is tried first (`awww query --json`, invoked with the
daemon's all-output option), followed by legacy `awww query` and `swww query`
text output. If several outputs use different images, output names are sorted
case-insensitively and the first valid output supplies the one global palette.
Normal startup/manual generation may fall back to the first image under
`~/Pictures/Wallpapers` or `~/Pictures`; the watcher uses daemon results only.

Ordinary wallpaper paths containing spaces are preserved as one argument. The
shell text interface does not guarantee filenames containing a newline.

#### Managed application themes

A normal `matugen-theme-sync apply --de niri` performs the integration
automatically:

- Niri receives a marked block at the end of `~/.config/niri/config.kdl` with
  `include "./colors.kdl"`. Because Niri includes are positional, the generated
  layout colors override earlier focus-ring, border, shadow, tab-indicator,
  overview, and recent-window colors.
- Waybar receives a complete managed `~/.config/waybar/style.css` that loads
  generated `colors.css`. Its module configuration is left untouched.
- Rofi receives the complete `themes/matugen.rasi` theme and a marked
  `@theme "matugen"` block in `config.rasi`; unrelated Rofi settings remain.
- Mako receives a complete managed `~/.config/mako/config` that includes the
  generated colors file.

Waybar, Rofi, and Mako are optional. Missing optional applications are reported
but do not prevent Niri theming; installed applications are reloaded when
possible, while Rofi reads its theme on its next launch. The watcher continues
polling the daemon and regenerates only when the selected wallpaper changes.

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
the whole managed lifecycle.

For a support-files-only setup pass,
`matugen-theme-sync apply --de niri --no-bootstrap` installs only the helper
scripts, Matugen config/templates, and service unit.
It does not create a backup or transaction, replace application themes, add
managed blocks, reload applications, or enable the watcher: application theme
takeover is zero until a normal apply.

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
