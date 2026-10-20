#!/usr/bin/env bash
# ARGON — instala la pantalla de arranque (Plymouth) y la de inicio de sesión (GDM).
# Uso:   sudo bash instalar-arranque-y-login.sh
# Revertir: sudo bash revertir-arranque-y-login.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Ejecuta este script con sudo: sudo bash $0" >&2
  exit 1
fi

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARGON="$(dirname "$AQUI")"
MARBLE="${MARBLE:-$(dirname "$ARGON")/third_party/Marble-shell-theme}"
USUARIO="${SUDO_USER:-$(logname 2>/dev/null || echo root)}"
FONDO="/home/$USUARIO/.local/share/backgrounds/argon-plasma-4k.png"
RESPALDO="$ARGON/instalar/respaldo-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RESPALDO"

echo "== 1/3 Respaldo de lo que hay ahora"
readlink -f /etc/alternatives/default.plymouth | tee "$RESPALDO/plymouth-anterior.txt"
readlink -f /etc/alternatives/gdm-theme.gresource | tee "$RESPALDO/gdm-anterior.txt"
cp -a /usr/share/gnome-shell/gnome-shell-theme.gresource "$RESPALDO/" 2>/dev/null || true
echo "   Respaldo en: $RESPALDO"

echo "== 2/3 Pantalla de arranque (Plymouth)"
install -d /usr/share/plymouth/themes/argon
install -m 644 "$ARGON"/plymouth-argon/{argon.plymouth,argon.script,orb.png,wordmark.png,bar-bg.png,bar-fg.png} \
  /usr/share/plymouth/themes/argon/
update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth \
  /usr/share/plymouth/themes/argon/argon.plymouth 200
update-alternatives --set default.plymouth /usr/share/plymouth/themes/argon/argon.plymouth
update-initramfs -u

echo "== 3/3 Pantalla de inicio de sesión (GDM, con Marble)"
command -v glib-compile-resources >/dev/null || apt-get install -y libglib2.0-dev-bin
cd "$MARBLE"
python3 install.py --gdm --hue 258 --name argon --mode dark \
  --gdm-image "$FONDO" --gdm-blur 40 --gdm-darken 35

# Marble registra su tema como "gtk-theme.gresource", pero Ubuntu elige el de GDM con "gdm-theme.gresource".
update-alternatives --set gdm-theme.gresource /usr/share/gnome-shell/gnome-shell-theme.gresource

chown -R "$USUARIO:$USUARIO" "$RESPALDO"
echo
echo "Listo. Lo verás en el próximo reinicio."
echo "Para volver atrás: sudo bash $AQUI/revertir-arranque-y-login.sh"
