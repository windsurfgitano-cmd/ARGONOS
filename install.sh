#!/usr/bin/env bash
# ARGON OS — instalador paso a paso.
#
# Convierte un Ubuntu con GNOME en ARGON OS: tema de vidrio verde phthalo con violeta argón,
# íconos, dock, efectos 3D, fondo animado, pantalla de arranque y de inicio de sesión, y
# (opcional) el asistente ARGON con su orbe en el panel.
#
# Uso rápido:
#   curl -fsSL https://raw.githubusercontent.com/windsurfgitano-cmd/ARGONOS/main/install.sh | bash
#
# Desde el repo:
#   ./install.sh                 pregunta paso a paso
#   ./install.sh --si            instala lo recomendado sin preguntar
#   ./install.sh --solo tema,iconos
#   ./install.sh --lista         muestra los componentes
#   ./install.sh --desinstalar   vuelve a como venía Ubuntu
set -euo pipefail

REPO_URL="${ARGONOS_REPO:-https://github.com/windsurfgitano-cmd/ARGONOS.git}"
RAMA="${ARGONOS_RAMA:-main}"
BASE="${XDG_DATA_HOME:-$HOME/.local/share}/argonos"
VERSION="0.1.0"

# --- Arranque: si llegó por curl | bash, baja el repo y se vuelve a llamar desde ahí ------------
AQUI=""
if [[ -n ${BASH_SOURCE[0]:-} && -f ${BASH_SOURCE[0]} ]]; then
  AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
if [[ -z "$AQUI" || ! -d "$AQUI/argon" || ! -d "$AQUI/config" ]]; then
  command -v git >/dev/null || { echo "Falta git: sudo apt install -y git" >&2; exit 1; }
  if [[ -d "$BASE/src/.git" ]]; then
    git -C "$BASE/src" pull --ff-only -q
  else
    mkdir -p "$BASE"
    git clone -q --depth 1 -b "$RAMA" "$REPO_URL" "$BASE/src"
  fi
  if { : </dev/tty; } 2>/dev/null; then
    exec bash "$BASE/src/install.sh" "$@" </dev/tty
  fi
  exec bash "$BASE/src/install.sh" "$@"
fi

ARGON="$AQUI/argon"
CONFIG="$AQUI/config"
TERCEROS="$BASE/third_party"
RESPALDO="$BASE/respaldos/$(date +%Y%m%d-%H%M%S)"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/argonos"
LOG="$LOG_DIR/instalacion-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$LOG_DIR"

# --- Apariencia ---------------------------------------------------------------------------------
if [[ -t 1 ]]; then
  V=$'\e[38;5;141m'; VD=$'\e[38;5;98m'; M=$'\e[38;5;79m'; G=$'\e[38;5;245m'; A=$'\e[38;5;179m'
  R=$'\e[38;5;203m'; B=$'\e[1m'; N=$'\e[0m'
else
  V=""; VD=""; M=""; G=""; A=""; R=""; B=""; N=""
fi

banner() {
  printf '\n%s' "$V"
  cat <<'ART'
     █████╗ ██████╗  ██████╗  ██████╗ ███╗   ██╗     ██████╗ ███████╗
    ██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗████╗  ██║    ██╔═══██╗██╔════╝
    ███████║██████╔╝██║  ███╗██║   ██║██╔██╗ ██║    ██║   ██║███████╗
    ██╔══██║██╔══██╗██║   ██║██║   ██║██║╚██╗██║    ██║   ██║╚════██║
    ██║  ██║██║  ██║╚██████╔╝╚██████╔╝██║ ╚████║    ╚██████╔╝███████║
    ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝     ╚═════╝ ╚══════╝
ART
  printf '%s    vidrio verde phthalo · brillo de argón · v%s%s\n\n' "$M" "$VERSION" "$N"
}

info()  { printf '  %s•%s %s\n' "$G" "$N" "$*"; }
ok()    { printf '  %s✓%s %s\n' "$M" "$N" "$*"; }
aviso() { printf '  %s!%s %s\n' "$A" "$N" "$*"; }
fallo() { printf '  %s✗%s %s\n' "$R" "$N" "$*"; }
morir() { fallo "$*"; printf '\n  Detalle en: %s\n' "$LOG"; exit 1; }

PASO_N=0; PASO_TOTAL=0
paso() {
  PASO_N=$((PASO_N + 1))
  printf '\n%s%s[%d/%d]%s %s%s%s\n' "$B" "$V" "$PASO_N" "$PASO_TOTAL" "$N" "$B" "$*" "$N"
  printf '%s──────────────────────────────────────────────────────────────%s\n' "$VD" "$N"
}

# Corre un comando con una ruedita; la salida va al registro.
correr() {
  local texto="$1"; shift
  printf '\n== %s\n$ %s\n' "$texto" "$*" >>"$LOG"
  if [[ ! -t 1 ]]; then
    "$@" >>"$LOG" 2>&1 && { ok "$texto"; return 0; } || { fallo "$texto"; return 1; }
  fi
  "$@" >>"$LOG" 2>&1 &
  local pid=$! i=0 marcos='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
  while kill -0 "$pid" 2>/dev/null; do
    printf '\r  %s%s%s %s' "$V" "${marcos:i++%${#marcos}:1}" "$N" "$texto"
    sleep 0.1
  done
  if wait "$pid"; then
    printf '\r\e[K'; ok "$texto"
  else
    printf '\r\e[K'; fallo "$texto"; return 1
  fi
}

SI=0
preguntar() {  # preguntar "¿Seguimos?" s|n  → 0 si la respuesta es sí
  local q="$1" def="${2:-s}" r
  if [[ $SI -eq 1 ]]; then [[ $def == s ]]; return; fi
  local hint="[S/n]"; [[ $def == n ]] && hint="[s/N]"
  printf '  %s?%s %s %s%s%s ' "$V" "$N" "$q" "$G" "$hint" "$N"
  read -r r || r=""
  r="${r,,}"; [[ -z $r ]] && r="$def"
  [[ $r == s* || $r == y* ]]
}

# --- Componentes --------------------------------------------------------------------------------
# id | título | descripción | recomendado (1/0) | necesita sudo (1/0)
COMPONENTES=(
  "paquetes|Paquetes base|git, Python con GTK 4, herramientas de GNOME y video|1|1"
  "tema|Tema ARGON|Marble violeta + capa de vidrio verde, modo oscuro, acento violeta, apps GTK 4|1|0"
  "iconos|Íconos|Colloid violeta oscuro|1|0"
  "extensiones|Dock y efectos|Dock de vidrio, desenfoque, cubo 3D, Coverflow, ventanas gelatina, círculos de escritorios|1|0"
  "fondo|Fondo de pantalla|Fondo ARGON fijo en escritorio y bloqueo|1|0"
  "fondo_animado|Fondo animado|Hanabi + video en bucle (se pausa con batería o ventana maximizada)|0|1"
  "terminal|Terminal|Paleta ARGON para Ptyxis con transparencia|1|0"
  "arranque|Arranque y login|Orbe de plasma al encender, pantalla de inicio de sesión ARGON y nombre \"ARGON OS\"|0|1"
  "asistente|Asistente ARGON|Orbe en el panel, ventana ARGON (Super+Espacio) y servicio argond · experimental|0|0"
  "voz|Voz del asistente|Whisper para escuchar y Piper para hablar (~600 MB) · experimental|0|0"
)
declare -A ELEGIDO=()

campo() { local IFS='|'; read -ra p <<<"$1"; printf '%s' "${p[$2]}"; }

listar() {
  local i=1 c
  for c in "${COMPONENTES[@]}"; do
    local id; id="$(campo "$c" 0)"
    local marca="${G}[ ]${N}"; [[ ${ELEGIDO[$id]:-0} -eq 1 ]] && marca="${M}[✓]${N}"
    local sudo=""; [[ "$(campo "$c" 4)" == 1 ]] && sudo=" ${A}(sudo)${N}"
    printf '   %s %2d. %s%s%s%s\n       %s%s%s\n' "$marca" "$i" "$B" "$(campo "$c" 1)" "$N" "$sudo" "$G" "$(campo "$c" 2)" "$N"
    i=$((i + 1))
  done
}

elegir_recomendados() {
  local c; for c in "${COMPONENTES[@]}"; do ELEGIDO[$(campo "$c" 0)]="$(campo "$c" 3)"; done
}

menu() {
  while true; do
    printf '\n%sQué quieres instalar%s  %s(escribe números para marcar o desmarcar, ej: 6 8 · "t" todo · Enter sigue)%s\n\n' "$B" "$N" "$G" "$N"
    listar
    printf '\n  %s›%s ' "$V" "$N"
    local r; read -r r || r=""
    [[ -z $r ]] && break
    if [[ $r == t ]]; then
      local c; for c in "${COMPONENTES[@]}"; do ELEGIDO[$(campo "$c" 0)]=1; done; continue
    fi
    local n
    for n in $r; do
      if [[ $n =~ ^[0-9]+$ ]] && (( n >= 1 && n <= ${#COMPONENTES[@]} )); then
        local id; id="$(campo "${COMPONENTES[n-1]}" 0)"
        ELEGIDO[$id]=$(( 1 - ${ELEGIDO[$id]:-0} ))
      fi
    done
  done
}

# --- Utilidades ---------------------------------------------------------------------------------
version_gnome() { gnome-shell --version 2>/dev/null | grep -oE '[0-9]+' | head -1; }

clonar() {  # clonar url carpeta [commit]
  local url="$1" dir="$TERCEROS/$2" rev="${3:-}"
  mkdir -p "$TERCEROS"
  if [[ -d "$dir/.git" ]]; then
    git -C "$dir" fetch -q --depth 50 origin
  else
    git clone -q --depth 50 "$url" "$dir"
  fi
  if [[ -n $rev ]]; then git -C "$dir" checkout -q "$rev"; else git -C "$dir" reset -q --hard origin/HEAD; fi
}

activar_extension() {
  local uuid="$1"
  python3 - "$uuid" <<'PY'
import ast, subprocess, sys
uuid = sys.argv[1]
def get(k):
    out = subprocess.run(["gsettings", "get", "org.gnome.shell", k], capture_output=True, text=True).stdout.strip()
    out = out.replace("@as ", "")
    return ast.literal_eval(out) if out else []
on, off = get("enabled-extensions"), get("disabled-extensions")
if uuid not in on: on.append(uuid)
off = [x for x in off if x != uuid]
subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions", str(on)], check=True)
subprocess.run(["gsettings", "set", "org.gnome.shell", "disabled-extensions", str(off)], check=True)
PY
  gnome-extensions enable "$uuid" 2>/dev/null || true
}

desactivar_extension() {
  local uuid="$1"
  gnome-extensions disable "$uuid" 2>/dev/null || true
  python3 - "$uuid" <<'PY'
import ast, subprocess, sys
uuid = sys.argv[1]
out = subprocess.run(["gsettings", "get", "org.gnome.shell", "enabled-extensions"], capture_output=True, text=True).stdout.strip()
on = ast.literal_eval(out.replace("@as ", "")) if out else []
subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions", str([x for x in on if x != uuid])], check=True)
PY
}

# Baja una extensión desde extensions.gnome.org para esta versión de GNOME.
instalar_extension_ego() {
  local uuid="$1" ver; ver="$(version_gnome)"
  local url
  url="$(curl -fsSL "https://extensions.gnome.org/extension-info/?uuid=${uuid}&shell_version=${ver}" |
         python3 -c 'import json,sys; print(json.load(sys.stdin).get("download_url",""))')" || return 1
  [[ -n $url ]] || return 1
  local zip; zip="$(mktemp --suffix=.zip)"
  curl -fsSL "https://extensions.gnome.org${url}" -o "$zip" && gnome-extensions install --force "$zip"
  local r=$?; rm -f "$zip"; return $r
}

sudo_listo=0
pedir_sudo() {
  [[ $sudo_listo -eq 1 ]] && return 0
  info "Algunos pasos tocan el sistema; te pido la contraseña de administrador una vez."
  sudo -v || morir "Sin permisos de administrador no puedo seguir con ese paso."
  sudo_listo=1
  ( while true; do sudo -n true 2>/dev/null; sleep 50; kill -0 "$$" 2>/dev/null || exit; done ) &
}

# --- Pasos --------------------------------------------------------------------------------------
paso_chequeo() {
  paso "Revisando tu equipo"
  [[ $EUID -ne 0 ]] || morir "No lo ejecutes con sudo; el instalador lo pide solo cuando hace falta."
  # shellcheck disable=SC1091
  . /etc/os-release 2>/dev/null || true
  local gv; gv="$(version_gnome)"
  info "Sistema: ${PRETTY_NAME:-desconocido}"
  [[ -n $gv ]] || morir "No encontré GNOME Shell. ARGON OS se instala sobre Ubuntu con GNOME."
  info "GNOME Shell $gv · sesión ${XDG_SESSION_TYPE:-?}"
  [[ ${ID:-} == ubuntu || ${ID_LIKE:-} == *ubuntu* ]] || aviso "Probado en Ubuntu. En ${NAME:-tu sistema} puede que algo no calce."
  (( gv >= 46 )) || morir "Necesitas GNOME 46 o más nuevo (Ubuntu 24.04 o posterior)."
  (( gv == 50 )) || aviso "Hecho y probado en GNOME 50 (Ubuntu 26.04). En GNOME $gv lo visual debería andar; el login puede variar."
  command -v gsettings >/dev/null || morir "Falta gsettings."
  ok "Todo listo para empezar"
}

paso_respaldo() {
  paso "Respaldo de tu configuración actual"
  mkdir -p "$RESPALDO"
  dconf dump / >"$RESPALDO/dconf-completo.ini"
  [[ -f $HOME/.config/gtk-4.0/gtk.css ]] && cp "$HOME/.config/gtk-4.0/gtk.css" "$RESPALDO/gtk4.css"
  ok "Guardado en $RESPALDO"
  info "Para volver exactamente a esto: dconf load / < \"$RESPALDO/dconf-completo.ini\""
}

paso_paquetes() {
  paso "Paquetes base"
  pedir_sudo
  local pk=(git curl unzip python3 python3-gi python3-pil python3-numpy python3-cairo gir1.2-gtk-4.0 gir1.2-adw-1
            gnome-shell-extensions gnome-shell-extension-prefs libglib2.0-dev-bin sassc dconf-cli)
  correr "Actualizando la lista de paquetes" sudo apt-get update -q || aviso "apt update falló; sigo con lo que hay"
  correr "Instalando ${#pk[@]} paquetes" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${pk[@]}" ||
    morir "No pude instalar los paquetes base."
}

paso_tema() {
  paso "Tema ARGON"
  correr "Bajando Marble (tema del panel y menús)" clonar https://github.com/imarkoff/Marble-shell-theme.git Marble-shell-theme ||
    morir "No pude bajar Marble."
  correr "Generando Marble-argon (violeta, tono 258)" bash -c "cd '$TERCEROS/Marble-shell-theme' && python3 install.py --hue 258 --name argon --mode dark" ||
    morir "Marble no se pudo generar."
  local css="$HOME/.themes/Marble-argon-dark/gnome-shell/gnome-shell.css"
  if [[ -f $css ]] && ! grep -q "ARGON: superficies de vidrio" "$css"; then
    cat "$CONFIG/marble-capa-argon.css" >>"$css"
  fi
  ok "Capa de vidrio verde aplicada"

  correr "Activando User Themes" activar_extension user-theme@gnome-shell-extensions.gcampax.github.com
  dconf write /org/gnome/shell/extensions/user-theme/name "'Marble-argon-dark'"
  gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark'
  gsettings set org.gnome.desktop.interface accent-color 'purple' 2>/dev/null || true
  if [[ -d /usr/share/themes/Yaru-purple-dark ]]; then
    gsettings set org.gnome.desktop.interface gtk-theme 'Yaru-purple-dark'
  fi
  mkdir -p "$HOME/.config/gtk-4.0"
  cp "$CONFIG/gtk4.css" "$HOME/.config/gtk-4.0/gtk.css"
  ok "Modo oscuro, acento violeta y apps GTK 4 con la paleta ARGON"
}

paso_iconos() {
  paso "Íconos"
  correr "Bajando Colloid" clonar https://github.com/vinceliuice/Colloid-icon-theme.git Colloid-icon-theme ||
    morir "No pude bajar Colloid."
  correr "Instalando Colloid violeta" bash -c "cd '$TERCEROS/Colloid-icon-theme' && ./install.sh -t purple" ||
    morir "Colloid no se pudo instalar."
  gsettings set org.gnome.desktop.interface icon-theme 'Colloid-Purple-Dark'
  ok "Íconos: Colloid-Purple-Dark"
}

EXTENSIONES=(
  "blur-my-shell@aunetx|vidrio en panel y vista general"
  "dash2dock-lite@icedman.github.com|dock de vidrio con animaciones"
  "desktop-cube@schneegans.github.com|escritorios en cubo 3D"
  "CoverflowAltTab@palatis.blogspot.com|Alt+Tab en 3D"
  "burn-my-windows@schneegans.github.com|efectos al abrir y cerrar ventanas"
  "compiz-windows-effect@hermes83.github.com|ventanas gelatina"
  "space-bar@luchrioh|círculos numerados de escritorios"
)

paso_extensiones() {
  paso "Dock y efectos"
  command -v gnome-extensions >/dev/null || morir "Falta el comando gnome-extensions (paquete gnome-shell)."
  local e uuid desc fallaron=0
  for e in "${EXTENSIONES[@]}"; do
    uuid="${e%%|*}"; desc="${e#*|}"
    if correr "$desc" instalar_extension_ego "$uuid"; then
      activar_extension "$uuid"
    else
      fallaron=$((fallaron + 1))
    fi
  done
  dconf load /org/gnome/shell/extensions/ <"$CONFIG/extensiones.dconf"
  # El dock de Ubuntu se apaga para que no haya dos.
  if gnome-extensions list 2>/dev/null | grep -q ubuntu-dock@ubuntu.com; then
    desactivar_extension ubuntu-dock@ubuntu.com
    info "Dock de Ubuntu desactivado (lo reemplaza el dock de vidrio)"
  fi
  ok "Ajustes de ARGON cargados en las extensiones"
  (( fallaron == 0 )) || aviso "$fallaron extensiones no estaban disponibles para GNOME $(version_gnome)."
  REINICIAR_SESION=1
}

paso_fondo() {
  paso "Fondo de pantalla"
  local dir="$HOME/.local/share/backgrounds/argon"
  mkdir -p "$dir"
  cp "$ARGON/fondos/argon-fondo-wan-fijo.png" "$ARGON/fondos/argon-humo-fijo.png" "$dir/"
  local uri="file://$dir/argon-fondo-wan-fijo.png"
  gsettings set org.gnome.desktop.background picture-uri "$uri"
  gsettings set org.gnome.desktop.background picture-uri-dark "$uri"
  gsettings set org.gnome.desktop.screensaver picture-uri "$uri"
  ok "Fondo y pantalla de bloqueo ARGON"
}

paso_fondo_animado() {
  paso "Fondo animado"
  pedir_sudo
  correr "Paquetes para compilar y reproducir video" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    meson ninja-build nodejs npm libgtk-4-media-gstreamer gstreamer1.0-plugins-good gstreamer1.0-libav gir1.2-gstreamer-1.0 ||
    morir "No pude instalar lo que necesita Hanabi."
  correr "Bajando Hanabi" clonar https://github.com/jeffshee/gnome-ext-hanabi.git gnome-ext-hanabi || morir "No pude bajar Hanabi."
  correr "Compilando e instalando Hanabi (tarda un poco)" bash -c "cd '$TERCEROS/gnome-ext-hanabi' && make install" ||
    morir "Hanabi no compiló. Mira el registro."
  local vdir; vdir="$(xdg-user-dir VIDEOS 2>/dev/null || echo "$HOME/Videos")/argon"
  mkdir -p "$vdir"
  cp "$ARGON/fondos/argon-fondo-wan-loop.mp4" "$vdir/"
  local h=/io/github/jeffshee/hanabi-extension
  dconf write $h/video-path "'$vdir/argon-fondo-wan-loop.mp4'"
  dconf write $h/mute true
  dconf write $h/pause-on-battery 2
  dconf write $h/pause-on-maximize-or-fullscreen 1
  dconf write $h/show-on-lock-screen false
  if lspci 2>/dev/null | grep -qiE 'vga.*intel|display.*intel'; then
    correr "Decodificación por hardware Intel" sudo apt-get install -y -q intel-media-va-driver && dconf write $h/enable-va true
  fi
  activar_extension hanabi-extension@jeffshee.github.io
  ok "Fondo animado listo (se ve al volver a entrar a la sesión)"
  REINICIAR_SESION=1
}

paso_terminal() {
  paso "Terminal"
  if ! command -v ptyxis >/dev/null; then
    aviso "No encontré Ptyxis (la terminal de Ubuntu 25.10+). Me salto este paso."
    return
  fi
  mkdir -p "$HOME/.local/share/org.gnome.Ptyxis/palettes"
  cp "$CONFIG/ptyxis-argon.palette" "$HOME/.local/share/org.gnome.Ptyxis/palettes/argon.palette"
  local uuid; uuid="$(gsettings get org.gnome.Ptyxis default-profile-uuid 2>/dev/null | tr -d "'")"
  if [[ -n $uuid ]]; then
    local p="org.gnome.Ptyxis.Profile:/org/gnome/Ptyxis/Profiles/$uuid/"
    gsettings set "$p" palette 'argon' || true
    gsettings set "$p" opacity 0.9 || true
  fi
  ok "Paleta ARGON en la terminal"
}

paso_arranque() {
  paso "Arranque y pantalla de inicio de sesión"
  aviso "Esto cambia Plymouth y GDM. Siempre puedes volver con: ./install.sh --desinstalar"
  preguntar "¿Seguimos con el arranque y el login?" s || { info "Saltado."; return; }
  pedir_sudo
  [[ -d $TERCEROS/Marble-shell-theme ]] || correr "Bajando Marble" clonar https://github.com/imarkoff/Marble-shell-theme.git Marble-shell-theme
  local fondo="$HOME/.local/share/backgrounds/argon/argon-fondo-wan-fijo.png"
  [[ -f $fondo ]] || fondo="$ARGON/fondos/argon-fondo-wan-fijo.png"

  correr "Pantalla de arranque (orbe de plasma)" sudo bash "$ARGON/instalar/actualizar-arranque.sh" || morir "Falló Plymouth."
  correr "Login con Marble" sudo bash -c "cd '$TERCEROS/Marble-shell-theme' && python3 install.py --gdm --hue 258 --name argon --mode dark --gdm-image '$fondo' --gdm-blur 40 --gdm-darken 35 && update-alternatives --set gdm-theme.gresource /usr/share/gnome-shell/gnome-shell-theme.gresource" ||
    aviso "Marble no pudo tematizar el login."
  if (( $(version_gnome) >= 50 )); then
    if correr "Armando el login ARGON para GNOME 50" bash -c "cd '$ARGON' && python3 herramientas/armar_tema_login.py"; then
      correr "Instalando el login ARGON" sudo bash "$ARGON/instalar/aplicar-tema-login.sh" || aviso "No se instaló el login ARGON."
    fi
  fi
  correr "Nombre \"ARGON OS\" en el login" sudo bash "$ARGON/instalar/aplicar-nombre-argon-os.sh" || aviso "No se aplicó el nombre."
  ok "Lo verás en el próximo reinicio"
  REINICIAR_EQUIPO=1
}

paso_asistente() {
  paso "Asistente ARGON"
  info "El asistente usa un modelo local por la API de Strata (127.0.0.1:8080) y Hermes (comando hermes)."
  command -v hermes >/dev/null || aviso "No encontré hermes: la ventana abre, pero sin Hermes no hay quien ejecute los pedidos."
  local data="$HOME/.local/share/argon" ext="$HOME/.local/share/gnome-shell/extensions/argon@argonos"
  mkdir -p "$data" "$HOME/.config/systemd/user" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/256x256/apps"
  install -m 644 "$ARGON/argond/argond.py" "$ARGON/argond/argon_mcp.py" "$ARGON/app/argon_app.py" "$data/"
  install -m 644 "$ARGON/argond/argond.service" "$HOME/.config/systemd/user/argond.service"
  install -m 644 "$ARGON/app/dev.argon.Argon.desktop" "$HOME/.local/share/applications/"
  install -m 644 "$ARGON/marca/icono-argon.png" "$HOME/.local/share/icons/hicolor/256x256/apps/argon.png"
  rm -rf "$ext"; cp -r "$ARGON/orbe/argon@argonos" "$ext"
  glib-compile-schemas "$ext/schemas" 2>>"$LOG" || true
  if [[ ! -f $HOME/.config/argon/argon.json ]]; then
    mkdir -p "$HOME/.config/argon"
    cp "$CONFIG/argon.ejemplo.json" "$HOME/.config/argon/argon.json"
    info "Tus ajustes (nombre, flota, carpetas): ~/.config/argon/argon.json"
  fi
  # Super+Espacio queda para ARGON; el cambio de idioma del teclado sigue en la tecla dedicada.
  gsettings set org.gnome.desktop.wm.keybindings switch-input-source "['XF86Keyboard']"
  gsettings set org.freedesktop.ibus.general.hotkey triggers "@as []" 2>/dev/null || true
  systemctl --user daemon-reload
  correr "Servicio argond" systemctl --user enable --now argond.service || aviso "argond no arrancó; mira: journalctl --user -u argond"
  activar_extension argon@argonos
  ok "Orbe y ventana ARGON instalados · Super+Espacio"
  REINICIAR_SESION=1
}

paso_voz() {
  paso "Voz del asistente"
  local data="$HOME/.local/share/argon"
  [[ -f $data/argond.py ]] || aviso "La voz es parte del asistente; instálalo también para usarla."
  pedir_sudo
  correr "Paquetes de audio" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-venv pipewire-bin ||
    morir "No pude instalar los paquetes de audio."
  correr "Entorno de Python para la voz" python3 -m venv "$data/voz" || morir "No pude crear el entorno."
  correr "faster-whisper y piper (tarda)" "$data/voz/bin/pip" install -q "faster-whisper==1.2.1" "piper-tts==1.8.0" numpy ||
    morir "No pude instalar las librerías de voz."
  local hf=https://huggingface.co w="$data/modelos/whisper-small" p="$data/modelos/piper"
  mkdir -p "$w" "$p"
  local f
  for f in config.json model.bin tokenizer.json vocabulary.txt; do
    [[ -s $w/$f ]] || correr "Whisper small: $f" curl -fsSL "$hf/Systran/faster-whisper-small/resolve/main/$f" -o "$w/$f" || morir "Falló la descarga de Whisper."
  done
  for f in es_MX-claude-high.onnx es_MX-claude-high.onnx.json; do
    [[ -s $p/$f ]] || correr "Voz Piper: $f" curl -fsSL "$hf/rhasspy/piper-voices/resolve/main/es/es_MX/claude/high/$f" -o "$p/$f" || morir "Falló la descarga de la voz."
  done
  install -m 644 "$ARGON/voz/argon_voz.py" "$data/"
  install -m 644 "$ARGON/voz/argon-voz.service" "$HOME/.config/systemd/user/"
  systemctl --user daemon-reload
  correr "Servicio argon-voz" systemctl --user enable --now argon-voz.service || aviso "argon-voz no arrancó."
}

# --- Desinstalar --------------------------------------------------------------------------------
desinstalar() {
  banner
  printf '%sVolver a como venía Ubuntu%s\n' "$B" "$N"
  preguntar "¿Quito ARGON OS de este usuario?" n || exit 0
  local e
  for e in "${EXTENSIONES[@]}" "argon@argonos|" "hanabi-extension@jeffshee.github.io|"; do desactivar_extension "${e%%|*}"; done
  activar_extension ubuntu-dock@ubuntu.com 2>/dev/null || true
  dconf reset /org/gnome/shell/extensions/user-theme/name
  local k
  for k in gtk-theme icon-theme color-scheme accent-color; do gsettings reset org.gnome.desktop.interface $k; done
  gsettings reset org.gnome.desktop.background picture-uri
  gsettings reset org.gnome.desktop.background picture-uri-dark
  gsettings reset org.gnome.desktop.screensaver picture-uri
  gsettings reset org.gnome.desktop.wm.keybindings switch-input-source
  gsettings reset org.freedesktop.ibus.general.hotkey triggers 2>/dev/null || true
  [[ -f $HOME/.config/gtk-4.0/gtk.css ]] && grep -q ARGON "$HOME/.config/gtk-4.0/gtk.css" && rm "$HOME/.config/gtk-4.0/gtk.css"
  systemctl --user disable --now argond.service argon-voz.service 2>/dev/null || true
  ok "Escritorio de vuelta a Ubuntu"
  if [[ -d /usr/share/plymouth/themes/argon || -f /usr/share/wayland-sessions/argon.desktop ]]; then
    if preguntar "¿Quito también el arranque y el login ARGON? (sudo)" s; then
      MARBLE="$TERCEROS/Marble-shell-theme" sudo -E bash "$ARGON/instalar/revertir-arranque-y-login.sh" >>"$LOG" 2>&1 &&
        ok "Arranque y login de Ubuntu" || aviso "Revisa $LOG"
    fi
  fi
  info "Tus respaldos siguen en $BASE/respaldos"
  info "Cierra sesión y vuelve a entrar para terminar."
}

ayuda() {
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
}

# --- Principal ----------------------------------------------------------------------------------
SOLO=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --si|--yes|-y) SI=1 ;;
    --todo) SI=1; SOLO="todo" ;;
    --solo) SOLO="$2"; shift ;;
    --solo=*) SOLO="${1#*=}" ;;
    --lista) elegir_recomendados; listar; exit 0 ;;
    --desinstalar|--uninstall) desinstalar; exit 0 ;;
    -h|--help|--ayuda) ayuda; exit 0 ;;
    *) echo "Opción desconocida: $1 (usa --ayuda)" >&2; exit 2 ;;
  esac
  shift
done

banner
printf '  Registro completo: %s%s%s\n' "$G" "$LOG" "$N"

elegir_recomendados
if [[ -n $SOLO ]]; then
  for c in "${COMPONENTES[@]}"; do ELEGIDO[$(campo "$c" 0)]=0; done
  if [[ $SOLO == todo ]]; then
    for c in "${COMPONENTES[@]}"; do ELEGIDO[$(campo "$c" 0)]=1; done
  else
    IFS=',' read -ra pedidos <<<"$SOLO"
    for id in "${pedidos[@]}"; do
      [[ -v "ELEGIDO[$id]" ]] || morir "No conozco el componente \"$id\" (usa --lista)."
      ELEGIDO[$id]=1
    done
  fi
elif [[ $SI -eq 0 ]]; then
  menu
fi

ORDEN=()
for c in "${COMPONENTES[@]}"; do
  id="$(campo "$c" 0)"; [[ ${ELEGIDO[$id]} -eq 1 ]] && ORDEN+=("$id")
done
[[ ${#ORDEN[@]} -gt 0 ]] || { info "No elegiste nada. Hasta pronto."; exit 0; }

PASO_TOTAL=$(( ${#ORDEN[@]} + 2 ))
printf '\n'
info "Voy a instalar: ${ORDEN[*]}"
preguntar "¿Empezamos?" s || exit 0

REINICIAR_SESION=0; REINICIAR_EQUIPO=0
paso_chequeo
paso_respaldo
for id in "${ORDEN[@]}"; do "paso_$id"; done

printf '\n%s%s  ARGON OS quedó instalado.%s\n\n' "$B" "$M" "$N"
if [[ $REINICIAR_EQUIPO -eq 1 ]]; then
  info "Reinicia el equipo para ver el arranque y el login nuevos."
elif [[ $REINICIAR_SESION -eq 1 ]]; then
  info "Cierra sesión y vuelve a entrar para que GNOME cargue las extensiones."
fi
info "Volver atrás: ./install.sh --desinstalar   (o: bash $BASE/src/install.sh --desinstalar)"
info "Respaldo de antes: $RESPALDO"
printf '\n'
