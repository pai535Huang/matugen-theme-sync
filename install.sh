#!/usr/bin/env bash
set -euo pipefail

APP_NAME="matugen-theme-sync"
REPO_URL="https://github.com/pai535Huang/matugen-theme-sync.git"

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$XDG_DATA_HOME/$APP_NAME"
LOCAL_BIN="$HOME/.local/bin"
APP_DIRS="$XDG_DATA_HOME/applications"

GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
BOLD='\033[1m'
RESET='\033[0m'

info() { printf "${BOLD}[%s]${RESET} %s\n" "$APP_NAME" "$*"; }
ok()   { printf "${GREEN}[%s] OK: %s${RESET}\n" "$APP_NAME" "$*"; }
warn() { printf "${YELLOW}[%s] WARN: %s${RESET}\n" "$APP_NAME" "$*"; }
error(){ printf "${RED}[%s] ERROR: %s${RESET}\n" "$APP_NAME" "$*"; }

usage() {
  cat <<EOF
Usage: ${0##*/} [install|uninstall]

  install (default)  install to $INSTALL_DIR and link the
                     $APP_NAME command into $LOCAL_BIN
  uninstall          remove everything this installer created
EOF
}

find_source() {
  local cand
  for cand in "$PWD" "$(dirname "${BASH_SOURCE[0]:-$0}")"; do
    if [[ -f "$cand/matugen/config-plasma.toml" && -d "$cand/bin" ]]; then
      printf '%s\n' "$cand"
      return 0
    fi
  done
  return 1
}

clone_source() {
  local tmp
  tmp="$(mktemp -d)"
  if command -v git >/dev/null 2>&1 \
    && GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/true \
       git clone --depth 1 "$REPO_URL" "$tmp/repo" >/dev/null 2>&1; then
    printf '%s\n' "$tmp/repo"
    return 0
  fi
  rm -rf "$tmp"
  return 1
}

install_files() {
  local src="$1"
  install -d "$INSTALL_DIR"
  cp -a "$src/bin" "$src/matugen" "$src/systemd" "$INSTALL_DIR/"
  cp "$src/install.sh" "$INSTALL_DIR/install.sh"
  chmod +x "$INSTALL_DIR/bin/"*
  ok "installed: $INSTALL_DIR"
}

link_command() {
  install -d "$LOCAL_BIN"
  ln -sfn "$INSTALL_DIR/bin/$APP_NAME" "$LOCAL_BIN/$APP_NAME"
  ok "command: $LOCAL_BIN/$APP_NAME -> $INSTALL_DIR/bin/$APP_NAME"
}

desktop_entry() {
  install -d "$APP_DIRS"
  cat > "$APP_DIRS/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Matugen Theme Sync
Comment=Deploy or remove the Matugen theme-sync pipeline for KDE Plasma / GNOME
Exec=$INSTALL_DIR/bin/$APP_NAME show-ui
Icon=preferences-desktop-theme
Terminal=false
Categories=Settings;DesktopSettings;Utility;
EOF
  ok "GUI entry: $APP_DIRS/$APP_NAME.desktop"
}

check_dependencies() {
  local missing=()
  command -v matugen >/dev/null 2>&1 || missing+=("matugen")
  command -v python3 >/dev/null 2>&1 || missing+=("python3")
  if ! python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1')" >/dev/null 2>&1; then
    missing+=("python-gobject gtk4 libadwaita")
  fi
  command -v gsettings >/dev/null 2>&1 || missing+=("gsettings (glib2)")
  if (( ${#missing[@]} )); then
    warn "missing dependencies: ${missing[*]}"
    printf '  install: sudo pacman -S matugen python-gobject gtk4 libadwaita glib2\n'
  else
    ok "dependencies OK"
  fi
}

check_path() {
  if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
    warn "$LOCAL_BIN is not in PATH; run: export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi
}

do_install() {
  local src
  info "installing $APP_NAME"
  src="$(find_source)" || src="$(clone_source)" || {
    error "cannot obtain the sources. Run this script from the repository, or install git "
    error "so it can be cloned from $REPO_URL automatically."
    return 1
  }
  [[ "$src" == "$PWD" ]] || info "source: $src"
  install_files "$src"
  link_command
  desktop_entry
  check_dependencies
  check_path
  echo
  ok "installed to $INSTALL_DIR"
  echo "  • next:    $APP_NAME apply      (deploy theme sync for the current desktop)"
  echo "  • GUI:      $APP_NAME show-ui"
  echo "  • status:   $APP_NAME status"
  echo "  • uninstall $INSTALL_DIR/install.sh uninstall"
  echo
  printf 'run apply for the current desktop now? [Y/n] '
  if read -r ans 2>/dev/null < /dev/tty; then
    [[ "$ans" =~ ^[Yy]?$ ]] && "$LOCAL_BIN/$APP_NAME" apply || true
  else
    info "no interactive terminal; skipping apply. Run '$APP_NAME apply' later."
  fi
}

do_uninstall() {
  info "uninstalling $APP_NAME"
  if [[ -x "$LOCAL_BIN/$APP_NAME" ]]; then
    printf 'also remove the deployed theme-sync pipeline (service + scripts)? [y/N] '
    if read -r ans 2>/dev/null < /dev/tty && [[ "$ans" =~ ^[Yy]$ ]]; then
      "$LOCAL_BIN/$APP_NAME" uninstall || true
    fi
  fi
  if [[ -L "$LOCAL_BIN/$APP_NAME" ]]; then
    if [[ "$(readlink "$LOCAL_BIN/$APP_NAME")" == "$INSTALL_DIR/bin/$APP_NAME" ]]; then
      rm -f "$LOCAL_BIN/$APP_NAME"
      ok "removed command link: $LOCAL_BIN/$APP_NAME"
    fi
  elif [[ -e "$LOCAL_BIN/$APP_NAME" ]]; then
    warn "$LOCAL_BIN/$APP_NAME is not a link to this installer; keeping it"
  fi
  rm -f "$APP_DIRS/$APP_NAME.desktop"
  ok "removed GUI entry: $APP_DIRS/$APP_NAME.desktop"
  if [[ -d "$INSTALL_DIR" ]]; then
    rm -rf "$INSTALL_DIR"
    ok "removed: $INSTALL_DIR"
  fi
  ok "uninstall done"
}

cmd="${1:-install}"
case "$cmd" in
  install) do_install ;;
  uninstall) do_uninstall ;;
  -h|--help|help) usage ;;
  *) usage; exit 2 ;;
esac
