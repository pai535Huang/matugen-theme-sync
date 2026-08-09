# Matugen Theme Sync

This project generates wallpaper-derived light and dark themes and keeps them
synchronized across KDE Plasma, GTK, terminals, editors, and other integrated
applications.

## Goal

- Generate both `MatugenLight.colors` and `MatugenDark.colors` from the current
  wallpaper.
- Treat selecting either generated KDE color scheme as the global light/dark
  mode switch.
- Synchronize GTK, Plasma, terminals, editors, and other integrated themes even
  when the wallpaper has not changed.
- Keep the implementation in scripts managed by a systemd user service rather
  than in a KWin script.

## Layout

- `bin/`: apply and watch scripts.
- `matugen/`: matugen configuration and source templates.
- `systemd/`: systemd user service units.

## Behavior

- Every matugen run generates both `MatugenLight.colors` and
  `MatugenDark.colors` from the same wallpaper.
- Selecting `MatugenLight` or `MatugenDark` in KDE System Settings switches the
  global mode without requiring a wallpaper change.
- Selecting another KDE color scheme suspends automatic synchronization.
- Wallpaper changes regenerate both KDE schemes and refresh all integrated
  applications in the currently selected mode.
- The apply path uses `flock`, separate wallpaper/mode state, and watcher
  debounce to prevent concurrent writes and feedback loops.

The active mode controls GTK 3/4, GNOME color preference, Plasma desktop theme,
Kitty, Neovim, btop, tmux, Zellij, Cava, Starship, Yazi, and the generated
qt5ct/qt6ct palettes. Some applications only read their theme when a new window
or session starts.

## Requirements

- `matugen`
- KDE Plasma 6 tools (`kreadconfig6`, `kwriteconfig6`, and
  `plasma-apply-colorscheme`)
- `inotify-tools` for immediate updates; a polling fallback is included
- `flock`, `python3`, and `curl`

## Deploy

Deploy the source files and bootstrap the two KDE schemes with:

```bash
install -Dm755 bin/matugen-plasma-apply "$HOME/.local/bin/matugen-plasma-apply"
install -Dm755 bin/matugen-plasma-watch "$HOME/.local/bin/matugen-plasma-watch"
install -Dm644 matugen/config.toml "$HOME/.config/matugen/config.toml"
install -Dm644 matugen/templates/* "$HOME/.config/matugen/templates/"
install -Dm644 systemd/matugen-plasma.service "$HOME/.config/systemd/user/matugen-plasma.service"
systemctl --user daemon-reload
"$HOME/.local/bin/matugen-plasma-apply" dark manual --force
systemctl --user enable matugen-plasma.service
systemctl --user restart matugen-plasma.service
```

After bootstrap, switch modes by selecting `MatugenLight` or `MatugenDark` in
KDE's Colors settings.

## Limitations

- Firefox and Obsidian files are generated, but this project cannot select a
  Firefox profile or Obsidian vault without user-specific paths.
- Zellij and some TUI applications may require a new session to load changes.
- The slideshow resolver uses the first image path exposed by Plasma's config;
  third-party wallpaper plugins vary in how they persist their current image.

The original design discussion is preserved in `docs/conversation.md`.
