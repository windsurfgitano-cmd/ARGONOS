#!/usr/bin/env bash
# ARGON — reinstala solo la pantalla de arranque (orbe de plasma animado).
# Uso: sudo bash actualizar-arranque.sh
# Revertir todo: sudo bash revertir-arranque-y-login.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Ejecuta este script con sudo: sudo bash $0" >&2
  exit 1
fi

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMA="$(dirname "$AQUI")/plymouth-argon"
DESTINO=/usr/share/plymouth/themes/argon

echo "== Copiando el tema (orbe animado, $(ls "$TEMA"/orb-*.png | wc -l) cuadros)"
rm -rf "$DESTINO"
install -d "$DESTINO"
install -m 644 "$TEMA"/*.plymouth "$TEMA"/*.script "$TEMA"/*.png "$DESTINO"/
update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth "$DESTINO/argon.plymouth" 200
update-alternatives --set default.plymouth "$DESTINO/argon.plymouth"

echo "== Regenerando la imagen de arranque (tarda un poco)"
update-initramfs -u
echo
echo "Listo. Lo verás en el próximo reinicio."
