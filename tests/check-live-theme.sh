#!/usr/bin/env bash
# Read-only live check: does everything that should follow the KDE colour
# scheme actually follow it right now?
#
# Run it INSIDE a kitty window (kitty is asked for its live background colour
# through the terminal itself, so the answer cannot be a stale file):
#
#     bash tests/check-live-theme.sh
#
# It writes nothing and signals nothing.
set -uo pipefail

HOME_DIR="$HOME"
KITTY_THEME="$HOME_DIR/.config/kitty/themes/Matugen.conf"
MODE="$(kreadconfig6 --file kdeglobals --group General --key ColorScheme 2>/dev/null || true)"
case "$MODE" in
  MatugenLight) EXPECT_MODE=light ;;
  MatugenDark)  EXPECT_MODE=dark ;;
  *)            EXPECT_MODE="" ;;
esac
if [[ "$EXPECT_MODE" == light ]]; then
  EXPECT_THEME="adw-gtk3"; EXPECT_DARK="false"
elif [[ "$EXPECT_MODE" == dark ]]; then
  EXPECT_THEME="adw-gtk3-dark"; EXPECT_DARK="true"
fi

ok()   { printf '  \033[32m✅\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m❌\033[0m %s\n' "$*"; }
note() { printf '     %s\n' "$*"; }

printf '\033[1m== KDE 当前配色方案 ==\033[0m\n'
printf '  ColorScheme = %s   (期望 light/dark = %s)\n\n' "${MODE:-<非 Matugen>}" "${EXPECT_MODE:-?}"

printf '\033[1m== kitty ==\033[0m\n'
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECT_BG="$(grep -m1 '^background' "$KITTY_THEME" 2>/dev/null | awk '{print $2}')"
CURRENT_CONF="$HOME_DIR/.config/kitty/current-theme.conf"
note "主题文件期望背景: ${EXPECT_BG:-<读取失败>}"

# File level first: this works in any shell and proves the apply step ran.
if [[ ! -f "$CURRENT_CONF" ]]; then
  bad "~/.config/kitty/current-theme.conf 不存在（apply 没写成功）"
elif cmp -s "$KITTY_THEME" "$CURRENT_CONF"; then
  ok "current-theme.conf 与 themes/Matugen.conf 一致（apply 侧正常，修改时间 $(stat -c '%y' "$CURRENT_CONF" | cut -c1-19)）"
else
  bad "current-theme.conf 与 themes/Matugen.conf 不一致（apply 侧没更新）"
fi

# Live check: ask the terminal itself. Only a terminal that implements OSC 11
# can answer, so a failure here says nothing about kitty itself.
BG_OUT="$(timeout 20 python3 "$HERE/kitty-live-background.py" 2>&1)"; BG_RC=$?
if (( BG_RC == 0 )); then
  if [[ "${BG_OUT,,}" == "${EXPECT_BG,,}" ]]; then
    ok "kitty 实时背景 $BG_OUT 与生成的主题一致"
  else
    bad "kitty 实时背景 $BG_OUT ≠ 主题文件里的 $EXPECT_BG（重载没生效）"
  fi
else
  if [[ -n "${KITTY_WINDOW_ID:-}" ]]; then
    bad "在 kitty 里，但终端没有回应 OSC 11 查询：$BG_OUT"
  else
    note "跳过实时查询（这个 shell 不在 kitty 窗口里）：$BG_OUT"
    note "想在 kitty 里核对，请在那个 kitty 窗口里运行同一个命令。"
  fi
fi
printf '\n'

printf '\033[1m== GTK (settings.ini 是 Plasma 下 GTK 真正读的地方) ==\033[0m\n'
if [[ -z "$EXPECT_MODE" ]]; then
  note "KDE 未在使用 MatugenLight/MatugenDark，跳过期望值比对"
else
  for version in 3 4; do
    file="$HOME_DIR/.config/gtk-$version.0/settings.ini"
    if [[ ! -f "$file" ]]; then
      bad "gtk-$version.0/settings.ini 不存在"
      continue
    fi
    theme="$(awk -F= '/^[ \t]*gtk-theme-name/{print $2; exit}' "$file" | tr -d ' \t')"
    dark="$(awk -F= '/^[ \t]*gtk-application-prefer-dark-theme/{print $2; exit}' "$file" | tr -d ' \t')"
    if [[ "$theme" == "$EXPECT_THEME" && "$dark" == "$EXPECT_DARK" ]]; then
      ok "gtk-$version.0: gtk-theme-name=$theme prefer-dark=$dark"
    else
      bad "gtk-$version.0: gtk-theme-name=$theme prefer-dark=$dark（期望 $EXPECT_THEME / $EXPECT_DARK）"
    fi
  done
fi
XSETTINGSD="$HOME_DIR/.config/xsettingsd/xsettingsd.conf"
if [[ -f "$XSETTINGSD" ]]; then
  note "xsettingsd.conf: $(awk '$1=="Net/ThemeName"{print "Net/ThemeName="$2}' "$XSETTINGSD") $(awk '$1=="Gtk/ApplicationPreferDarkTheme"{print "prefer-dark="$2}' "$XSETTINGSD")"
fi
if [[ -n "$EXPECT_MODE" ]]; then
  LIVE_GTK="$(timeout 25 python3 - <<'PY' 2>/dev/null
try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    settings = Gtk.Settings.get_default()
    print('%s|%s' % (settings.get_property('gtk-theme-name'),
                     settings.get_property('gtk-application-prefer-dark-theme')))
except Exception:
    pass
PY
)"
  if [[ -z "$LIVE_GTK" ]]; then
    note "GTK3 探针不可用（缺 python-gobject）"
  else
    IFS='|' read -r live_theme live_dark <<<"$LIVE_GTK"
    expected_dark_bool=False
    [[ "$EXPECT_DARK" == true ]] && expected_dark_bool=True
    if [[ "$live_theme" == "$EXPECT_THEME" && "$live_dark" == "$expected_dark_bool" ]]; then
      ok "GTK3 进程实际生效: theme=$live_theme prefer-dark=$live_dark"
    else
      bad "GTK3 进程实际生效: theme=$live_theme prefer-dark=$live_dark（期望 $EXPECT_THEME / $expected_dark_bool）"
    fi
  fi
fi
portal="$(timeout 15 gdbus call --session --dest org.freedesktop.portal.Desktop \
  --object-path /org/freedesktop/portal/desktop \
  --method org.freedesktop.portal.Settings.Read org.freedesktop.appearance color-scheme 2>/dev/null \
  | tr -dc '0-9' | tail -c1)"
case "$portal" in
  0) note "portal color-scheme = 0 (无偏好)" ;;
  1) note "portal color-scheme = 1 (偏好暗色)" ;;
  2) note "portal color-scheme = 2 (偏好亮色)" ;;
  *) note "portal color-scheme 查询失败" ;;
esac
printf '\n'
printf '说明：GTK4/libadwaita 与 Chrome 还会读 portal 的 color-scheme；\n'
printf '      GTK3 与 Chrome 的 GTK 主题模式读 settings.ini / XSETTINGS。\n'
