#!/usr/bin/env bash
set -euo pipefail

APP_NAME="matugen-theme-sync"
REPO_URL="https://github.com/pai535Huang/matugen-theme-sync.git"

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$XDG_DATA_HOME/$APP_NAME"
LOCAL_BIN="$HOME/.local/bin"
APP_DIRS="$XDG_DATA_HOME/applications"
MATUGEN_INSTALL_TTY="${MATUGEN_INSTALL_TTY:-/dev/tty}"
PACMAN_CONFIG_FILE="${PACMAN_CONFIG_FILE:-/etc/pacman.conf}"
MATUGEN_INSTALL_EUID="${MATUGEN_INSTALL_EUID:-$EUID}"

GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
BOLD='\033[1m'
RESET='\033[0m'

info() { printf "${BOLD}[%s]${RESET} %s\n" "$APP_NAME" "$*"; }
ok()   { printf "${GREEN}[%s] OK: %s${RESET}\n" "$APP_NAME" "$*"; }
warn() { printf "${YELLOW}[%s] WARN: %s${RESET}\n" "$APP_NAME" "$*"; }
error(){ printf "${RED}[%s] ERROR: %s${RESET}\n" "$APP_NAME" "$*" >&2; }

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
  # 全量重装: 先清掉旧安装副本, 避免 cp -a 只增不删导致废弃文件残留
  if [[ "$(basename "$INSTALL_DIR")" != "$APP_NAME" ]]; then
    error "refusing to remove unexpected directory: $INSTALL_DIR"
    return 1
  fi
  rm -rf "$INSTALL_DIR"
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

run_as_root() {
  if (( MATUGEN_INSTALL_EUID == 0 )); then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    error "sudo is required to install matugen"
    return 1
  fi
}

detect_package_manager() {
  if command -v pacman >/dev/null 2>&1 && [[ -f "$PACMAN_CONFIG_FILE" ]]; then
    printf '%s\n' pacman
  elif command -v dnf >/dev/null 2>&1; then
    printf '%s\n' dnf
  elif command -v apt-get >/dev/null 2>&1; then
    printf '%s\n' apt-get
  else
    return 1
  fi
}

matugen_available() {
  command -v matugen >/dev/null 2>&1 || [[ -x "$LOCAL_BIN/matugen" ]]
}

confirm_matugen_install() {
  local answer
  printf 'matugen is required but not installed. Install it now? [y/N] '
  if ! read -r answer 2>/dev/null < "$MATUGEN_INSTALL_TTY"; then
    error "matugen is required; no interactive terminal is available"
    return 1
  fi
  [[ "${answer,,}" == y || "${answer,,}" == yes ]]
}

install_matugen() {
  local manager="$1"
  case "$manager" in
    pacman)
      run_as_root pacman -S --needed --noconfirm matugen
      ;;
    dnf)
      run_as_root dnf -y install matugen
      ;;
    apt-get)
      run_as_root apt-get update || return 1
      run_as_root apt-get install -y cargo || return 1
      command -v cargo >/dev/null 2>&1 || {
        error "cargo is unavailable after apt installation"
        return 1
      }
      cargo install --root "$HOME/.local" matugen
      ;;
    *)
      error "unsupported package manager: $manager"
      return 1
      ;;
  esac
}

ensure_matugen() {
  local manager
  matugen_available && {
    ok "matugen dependency OK"
    return 0
  }
  if ! confirm_matugen_install; then
    error "matugen is required; installation cancelled"
    return 1
  fi
  manager="$(detect_package_manager)" || {
    error "no supported package manager found (pacman, dnf, apt)"
    return 1
  }
  info "installing matugen with $manager"
  install_matugen "$manager" || {
    error "failed to install matugen"
    return 1
  }
  matugen_available || {
    error "matugen installation finished, but the executable was not found"
    return 1
  }
  ok "matugen installed"
}

check_dependencies() {
  local missing=()
  command -v python3 >/dev/null 2>&1 || missing+=("python3")
  if ! python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1')" >/dev/null 2>&1; then
    missing+=("python-gobject gtk4 libadwaita")
  fi
  command -v gsettings >/dev/null 2>&1 || missing+=("gsettings (glib2)")
  if (( ${#missing[@]} )); then
    warn "missing dependencies: ${missing[*]}"
    printf '  install them with your distribution package manager\n'
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
  ensure_matugen || return 1
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

main() {
  local cmd="${1:-install}"
  case "$cmd" in
    install) do_install ;;
    uninstall) do_uninstall ;;
    -h|--help|help) usage ;;
    *) usage; return 2 ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
