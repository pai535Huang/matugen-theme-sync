# Matugen Theme Sync

Generate wallpaper-derived light/dark themes with [matugen](https://github.com/InioX/matugen) and keep them synchronized across your desktop. Auto-detects **KDE Plasma** or **GNOME** and deploys the matching config, helper scripts, and systemd user service with one command — or one GUI click.

## Features

- One command / GUI to install, apply, or remove the whole theming pipeline for your current desktop
- KDE Plasma: wallpaper + selected `MatugenLight`/`MatugenDark` color scheme drive global light/dark sync
- GNOME: follows `org.gnome.desktop.interface color-scheme`; GTK, GNOME Shell, and apps refresh on change
- Themes GTK 3/4, GNOME color preference, Kitty, Neovim, btop, tmux, Zellij, Cava, Starship, Yazi, qt5ct/qt6ct
- Writes a pywal-compatible scheme to `~/.cache/wal/colors.json` so pywal/pywalfox software follows along

## Requirements

- `matugen`, `python3`, `flock`, `curl`
- KDE Plasma: `kreadconfig6`, `kwriteconfig6`, `plasma-apply-colorscheme`, `inotify-tools`
- GNOME: `gsettings`
- GUI: `python-gobject`, `gtk4`, `libadwaita`

```bash
sudo pacman -S matugen python-gobject gtk4 libadwaita glib2 inotify-tools
```

## Install

```bash
# from a checkout:
./install.sh

# or straight from GitHub:
curl -fsSL https://raw.githubusercontent.com/pai535Huang/matugen-theme-sync/main/install.sh | sh
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

Options: `--de plasma|gnome` to force a desktop, `--no-bootstrap` to apply without generating a theme, `--purge` to also remove `~/.config/matugen`.

## Layout

- `bin/` — CLI + GUI and per-desktop apply/watch helpers
- `matugen/` — matugen configs and shared templates
- `systemd/` — user service units
- `install.sh` — installer / uninstaller
