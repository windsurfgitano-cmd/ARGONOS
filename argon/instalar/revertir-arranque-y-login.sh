#!/usr/bin/env bash
# ARGON — vuelve a la pantalla de arranque y de inicio de sesión de Ubuntu.
# Uso: sudo bash revertir-arranque-y-login.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Ejecuta este script con sudo: sudo bash $0" >&2
  exit 1
fi

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARBLE="${MARBLE:-$(dirname "$(dirname "$AQUI")")/third_party/Marble-shell-theme}"

echo "== Pantalla de arranque: vuelve el tema de Ubuntu"
update-alternatives --set default.plymouth /usr/share/plymouth/themes/bgrt/bgrt.plymouth
update-alternatives --remove default.plymouth /usr/share/plymouth/themes/argon/argon.plymouth || true
rm -rf /usr/share/plymouth/themes/argon
update-initramfs -u

echo "== Pantalla de inicio de sesión: Marble restaura su respaldo"
cd "$MARBLE"
python3 install.py --gdm -r || {
  ULTIMO="$(ls -d "$AQUI"/respaldo-* 2>/dev/null | tail -1)"
  if [[ -n "$ULTIMO" && -f "$ULTIMO/gnome-shell-theme.gresource" ]]; then
    cp -a "$ULTIMO/gnome-shell-theme.gresource" /usr/share/gnome-shell/
    echo "   Restaurado desde $ULTIMO"
  fi
}
# Ubuntu elige el tema de GDM con una alternativa; se devuelve a Yaru.
update-alternatives --set gdm-theme.gresource /usr/share/gnome-shell/theme/Yaru/gnome-shell-theme.gresource || true
update-alternatives --remove gdm-theme.gresource /usr/share/gnome-shell/theme/argon/gnome-shell-theme.gresource 2>/dev/null || true
rm -rf /usr/share/gnome-shell/theme/argon

echo "== Nombre ARGON OS: vuelve el logo y la sesión de Ubuntu"
rm -f /usr/share/glib-2.0/schemas/90_argon.gschema.override /usr/share/argon/argon-os-logo.png
glib-compile-schemas /usr/share/glib-2.0/schemas/
busctl call org.freedesktop.Accounts "/org/freedesktop/Accounts/User$(id -u "${SUDO_USER:-$(logname 2>/dev/null || echo root)}")" \
    org.freedesktop.Accounts.User SetSession s ubuntu || true
rm -f /usr/share/wayland-sessions/argon.desktop

echo
echo "Listo. En el próximo reinicio vuelve lo de Ubuntu."
