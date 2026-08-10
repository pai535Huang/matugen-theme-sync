# Matugen Theme Sync

This project generates wallpaper-derived light and dark themes and keeps them
synchronized across your desktop environment. It supports **KDE Plasma** and
**GNOME** in a single project: the desktop environment is detected
automatically and the matching matugen configuration, helper scripts, and
systemd user service are deployed.

## Goal

- One command and one GUI to install or remove the whole theming pipeline for
  the desktop you are currently running.
- KDE Plasma: wallpaper and the selected `MatugenLight` / `MatugenDark` KDE
  color scheme drive global light/dark synchronization.
- GNOME: wallpaper changes (via gsettings) regenerate the theme, and the
  official light/dark setting (`org.gnome.desktop.interface color-scheme`)
  switches matugen between light and dark generation; GTK, GNOME Shell and all
  integrated apps are refreshed.
- The active mode also controls GTK 3/4, GNOME color preference, Kitty, Neovim,
  btop, tmux, Zellij, Cava, Starship, Yazi, and qt5ct/qt6ct palettes.

## Layout

- `bin/matugen-theme-sync`: the CLI + GTK4/libadwaita GUI program.
- `bin/matugen-plasma-apply`, `bin/matugen-plasma-watch`: KDE Plasma helpers.
- `bin/matugen-gnome-apply`, `bin/matugen-gnome-watch`: GNOME helpers (from
  the `gnome-dotfiles` repo).
- `matugen/config-plasma.toml`, `matugen/config-gnome.toml`: matugen
  configurations, selected by the detected desktop environment.
- `matugen/templates/`: source templates shared by both configurations.
- `systemd/`: systemd user service units for each desktop environment.
- `install.sh`: one-click installer / uninstaller.

## Usage

The program detects the desktop environment automatically from your session
(`XDG_CURRENT_DESKTOP` etc.) and displays it.

## Installation

### One-click installer (recommended)

Works from the repository or straight from GitHub, no root required:

```bash
# from a checkout of this repository:
./install.sh

# or directly from GitHub:
curl -fsSL https://raw.githubusercontent.com/pai535Huang/matugen-theme-sync/main/install.sh | sh
```

The installer copies the program into `~/.local/share/matugen-theme-sync/`,
links the `matugen-theme-sync` command into `~/.local/bin/`, and adds a
"Matugen Theme Sync" entry to your application menu. It checks the
dependencies (matugen, python-gobject, gtk4, libadwaita) and asks whether to
run `apply` right away.

Remove everything it installed with:

```bash
~/.local/share/matugen-theme-sync/install.sh uninstall
```

### Run from the repository

```bash
bin/matugen-theme-sync status
bin/matugen-theme-sync show-ui
```

### Command line

```bash
matugen-theme-sync status    # show the detected desktop environment + install state
matugen-theme-sync apply     # deploy scripts, write matugen config, register + enable the systemd service,
                             # then generate the first theme immediately
matugen-theme-sync uninstall # stop the service, delete the service file and the helper scripts
matugen-theme-sync show-ui   # open the GTK4 / libadwaita GUI
```

Options:

- `apply --no-bootstrap` — install without generating a theme first.
- `uninstall --purge` — also remove `~/.config/matugen` (config + templates).
- `apply --de plasma|gnome` / `uninstall --de plasma|gnome` — force a desktop
  environment instead of auto-detecting (mainly for testing).

### GUI

`matugen-theme-sync show-ui` opens a libadwaita window that shows the current
desktop environment and offers two buttons:

- **应用 (Apply)** — runs `matugen-theme-sync apply`.
- **卸载 (Uninstall)** — asks for confirmation, then runs
  `matugen-theme-sync uninstall`.

Every command's output is streamed into the window so you can watch progress
and the final result.

## What apply does

1. Installs the helper scripts into `~/.local/bin/`.
2. Links `~/.local/bin/matugen-theme-sync` to this program.
3. Writes the desktop-specific matugen config as `~/.config/matugen/config.toml`.
4. Copies all templates into `~/.config/matugen/templates/`.
5. Installs the matching unit as `~/.config/systemd/user/matugen-*.service`.
6. Runs `systemctl --user daemon-reload` and `systemctl --user enable --now`.
7. Runs the apply script once so the theme is generated immediately.

## What uninstall does

1. Stops and disables the service.
2. Deletes the service file and runs `systemctl --user daemon-reload`.
3. Deletes the helper scripts and the `matugen-theme-sync` link.
4. Leaves `~/.config/matugen` intact unless `--purge` is given.

## Requirements

- `matugen`
- `python3`
- KDE Plasma: `kreadconfig6`, `kwriteconfig6`, `plasma-apply-colorscheme`
- GNOME: `gsettings`
- `inotify-tools` for immediate KDE updates (a polling fallback is included)
- `flock`, `curl`
- GUI: `python-gobject`, `gtk4`, `libadwaita`
  (`sudo pacman -S python-gobject gtk4 libadwaita`)

## Run from the repository

```bash
# from the repo root
bin/matugen-theme-sync status
bin/matugen-theme-sync show-ui
```

After the first `apply`, `~/.local/bin/matugen-theme-sync` points at this
program, so the bare command works everywhere on your PATH.

## Switching desktop environments

Just `apply` again after logging into the other desktop: the new environment is
detected, the matching config is written, and the matching service is
registered. Uninstall a desktop's pipeline the same way.
