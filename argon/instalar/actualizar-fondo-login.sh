#!/usr/bin/env bash
# ARGON — cambia el fondo de la pantalla de inicio de sesión al fondo actual (humo verde + plasma).
# No toca la pantalla de arranque.
# Uso: sudo bash actualizar-fondo-login.sh [imagen]
# Revertir todo: sudo bash revertir-arranque-y-login.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Ejecuta este script con sudo: sudo bash $0" >&2
  exit 1
fi

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARGON="$(dirname "$AQUI")"
MARBLE="${MARBLE:-$(dirname "$ARGON")/third_party/Marble-shell-theme}"
FONDO="${1:-$ARGON/fondos/argon-humo-fijo.png}"

if [[ ! -f "$FONDO" ]]; then
  echo "No encuentro la imagen: $FONDO" >&2
  exit 1
fi

echo "== Pantalla de inicio de sesión con: $FONDO"
cd "$MARBLE"
python3 install.py --gdm --hue 258 --name argon --mode dark --gdm-image "$FONDO"

# Marble registra su tema como "gtk-theme.gresource", pero Ubuntu elige el de GDM con "gdm-theme.gresource".
update-alternatives --set gdm-theme.gresource /usr/share/gnome-shell/gnome-shell-theme.gresource

echo
echo "Listo. Lo verás la próxima vez que cierres sesión o reinicies."
