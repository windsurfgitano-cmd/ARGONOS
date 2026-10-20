#!/usr/bin/env bash
# Pantalla de inicio de sesión: "ARGON OS" en vez de Ubuntu.
#  - el logo de abajo (el de Ubuntu) pasa a ser el de ARGON OS;
#  - la sesión se llama "ARGON OS" (es la misma sesión de Ubuntu con otro nombre) y queda como la tuya.
# Uso: sudo bash argon/instalar/aplicar-nombre-argon-os.sh     Deshacer: revertir-arranque-y-login.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Ejecútalo con sudo."; exit 1; }
AQUI="$(cd "$(dirname "$0")/.." && pwd)"
USUARIO="${SUDO_USER:-$(logname 2>/dev/null || echo root)}"

echo "== Logo de la pantalla de inicio de sesión"
install -D -m 644 "$AQUI/login-argon/argon-os-logo.png" /usr/share/argon/argon-os-logo.png
cat > /usr/share/glib-2.0/schemas/90_argon.gschema.override <<'OVR'
# ARGON OS: reemplaza el logo de Ubuntu (10_ubuntu-settings) en la pantalla de inicio de sesión.
[org.gnome.login-screen]
logo='/usr/share/argon/argon-os-logo.png'
OVR
glib-compile-schemas /usr/share/glib-2.0/schemas/

echo "== Sesión \"ARGON OS\""
sed -e 's/^Name=.*/Name=ARGON OS/' -e 's/^Comment=.*/Comment=ARGON OS (GNOME de Ubuntu con la capa ARGON)/' \
    /usr/share/wayland-sessions/ubuntu.desktop > /usr/share/wayland-sessions/argon.desktop
chmod 644 /usr/share/wayland-sessions/argon.desktop
UID_USUARIO="$(id -u "$USUARIO")"
busctl call org.freedesktop.Accounts "/org/freedesktop/Accounts/User$UID_USUARIO" \
    org.freedesktop.Accounts.User SetSession s argon

echo
echo "Listo. Se ve la próxima vez que aparezca la pantalla de inicio de sesión (cierra sesión o reinicia)."
