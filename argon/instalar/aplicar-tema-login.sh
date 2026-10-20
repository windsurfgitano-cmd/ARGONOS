#!/usr/bin/env bash
# ARGON — instala el tema de la pantalla de inicio de sesión (elegir usuario y escribir la contraseña).
# Antes: python3 herramientas/armar_tema_login.py   (desde argon/, sin sudo)
# Uso:   sudo bash aplicar-tema-login.sh
# Revertir: sudo bash revertir-arranque-y-login.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Ejecuta este script con sudo: sudo bash $0" >&2
  exit 1
fi

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGEN="$(dirname "$AQUI")/login-argon/gnome-shell-theme.gresource"
DESTINO=/usr/share/gnome-shell/theme/argon/gnome-shell-theme.gresource

if [[ ! -f "$ORIGEN" ]]; then
  echo "Falta $ORIGEN. Ármalo primero con: python3 herramientas/armar_tema_login.py" >&2
  exit 1
fi

echo "== Tema actual de la pantalla de inicio de sesión: $(readlink -f /etc/alternatives/gdm-theme.gresource)"
install -d "$(dirname "$DESTINO")"
install -m 644 "$ORIGEN" "$DESTINO"
update-alternatives --install /usr/share/gnome-shell/gdm-theme.gresource gdm-theme.gresource "$DESTINO" 5
update-alternatives --set gdm-theme.gresource "$DESTINO"
echo "== Ahora: $(readlink -f /etc/alternatives/gdm-theme.gresource)"
echo
echo "Listo. Lo verás la próxima vez que cierres sesión o reinicies."
