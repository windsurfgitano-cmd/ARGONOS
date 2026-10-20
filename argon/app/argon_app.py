#!/usr/bin/env python3
"""ARGON — la ventana del asistente.

Muestra el historial de conversaciones y, en cada mensaje, lo que Black Hat va haciendo en vivo (los events de
argond): su razonamiento, cada comando con su resultado, el texto de la respuesta y las tarjetas de permiso con
sus botones. Adjunta fotos y documentos. Todo el trabajo lo hace argond: cerrar esta ventana no detiene nada.
Se mueve a cualquier pantalla como cualquier ventana.
"""
import json
import os
import random
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

GObjectBinding = GObject.BindingFlags

APP_ID = "dev.argon.Argon"
API = "http://127.0.0.1:8737"
VOICE_API = "http://127.0.0.1:8738"
SETTINGS_PATH = os.path.join(GLib.get_user_data_dir(), "argon", "ventana.json")
ATTACH_DIR = os.path.join(GLib.get_user_data_dir(), "argon", "adjuntos")
TOKEN_PATH = os.path.join(GLib.get_user_data_dir(), "argon", "token")
FRAMES_DIR = os.path.join(GLib.get_user_data_dir(), "gnome-shell", "extensions", "argon@argonos", "orb-frames")
ACTIVE = ("pensando", "ejecutando", "esperando confirmación", "necesita tu permiso")
BUSY = ("pensando", "ejecutando", "necesita tu permiso")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

STATUS_STYLE = {
    "pensando": ("Trabajando…", "st-busy"),
    "necesita tu permiso": ("Necesita tu permiso", "st-wait"),
    "esperando confirmación": ("Esperaba confirmación", "st-off"),
    "ejecutando": ("Trabajando…", "st-busy"),
    "hecho": ("Hecho", "st-ok"),
    "respondido": ("Respondido", "st-ok"),
    "falló": ("Falló", "st-bad"),
    "cancelado": ("Detenido", "st-off"),
    "interrumpido": ("Interrumpido", "st-off"),
}
STEP_STYLE = {"pendiente": ("○", "st-off"), "en curso": ("…", "st-busy"), "hecho": ("✓", "st-ok"),
              "falló": ("✕", "st-bad"), "cancelado": ("–", "st-off")}
TOOL_STYLE = {"pending": ("○", "st-off"), "in_progress": ("◌", "st-busy"), "completed": ("●", "st-ok"),
              "failed": ("✕", "st-bad")}
PLAN_MARK = {"pending": "○", "in_progress": "…", "completed": "✓"}
# Lo que dice el orbe mientras trabaja (como los verbos de Claude Code, pero con argón).
BUSY_WORDS = ["Ionizando", "Plasmatizando", "Excitando electrones", "Destilando argón", "Calentando el plasma",
              "Alineando electrones", "Consultando al gas noble", "Maquinando", "Cocinando", "Hilando fino",
              "Rumiando", "Cachando", "Achuntándole", "Orquestando", "Descifrando", "Tejiendo", "Puliendo",
              "Brillando en violeta", "Cuadrando la flota", "Haciendo magia negra (de la buena)"]
YES_WORDS = ("sí", "si", "dale", "ejecuta", "ejecútalo", "hazlo", "confirmo", "adelante", "ya", "ok", "okay",
             "listo", "permite", "permítelo", "envía", "envíalo", "manda")
NO_WORDS = ("no", "descarta", "cancela", "olvídalo", "déjalo", "rechaza")
TOOL_NAMES = {"abrir_app": "App", "abrir_carpeta": "Carpeta", "ir_a_escritorio": "Escritorio",
              "modo_foco": "Modo foco", "quitar_modo_foco": "Modo foco", "delegar_black_hat": "Black Hat",
              "encargo_flota": "la flota"}

CSS = """
.argon-title { font-weight: 300; letter-spacing: 6px; }
.bubble-user { background-color: alpha(#7a5cf0, 0.22); border: 1px solid alpha(#a48bff, 0.35);
               border-radius: 14px; padding: 10px 14px; }
.bubble-argon { background-color: alpha(#cfe9dd, 0.05); border: 1px solid alpha(#cfe9dd, 0.10);
                border-radius: 14px; padding: 10px 14px; }
.step-card { background-color: alpha(#cfe9dd, 0.04); border: 1px solid alpha(#cfe9dd, 0.10);
             border-radius: 12px; padding: 10px 12px; }
.tool-chip { font-size: 0.8em; padding: 1px 8px; border-radius: 999px; border: 1px solid alpha(#cfe9dd, 0.2); }
.brief { font-family: monospace; font-size: 0.85em; background-color: alpha(#a48bff, 0.08);
         border: 1px solid alpha(#a48bff, 0.25); border-radius: 8px; padding: 8px 10px; }
.output { font-family: monospace; font-size: 0.88em; }
.st-ok { color: #3ee0a0; } .st-bad { color: #ff5d6d; } .st-wait { color: #c9b7ff; }
.st-busy { color: #e7c27a; } .st-off { color: alpha(#cfe9dd, 0.5); }
.composer { padding: 10px 14px 14px 14px; }
.busy-line { color: #c9b7ff; font-weight: 600; }
.term { background-color: alpha(#000000, 0.35); border: 1px solid alpha(#cfe9dd, 0.08);
        border-radius: 10px; padding: 8px 10px; font-family: monospace; font-size: 0.86em; }
.term-cmd { color: #c9b7ff; } .term-tool { color: #8fd8ff; }
.term-ok { color: alpha(#cfe9dd, 0.72); } .term-err { color: #ff8f9c; }
.mic-on { background-color: #c0354a; color: white; }
.perm-card { background-color: alpha(#7a5cf0, 0.12); border: 1px solid alpha(#a48bff, 0.6);
             border-radius: 12px; padding: 12px 14px; }
.thought { font-size: 0.9em; font-style: italic; color: alpha(#cfe9dd, 0.55); }
.attach-chip { background-color: alpha(#cfe9dd, 0.07); border: 1px solid alpha(#cfe9dd, 0.15);
               border-radius: 999px; padding: 2px 4px 2px 10px; }
.thumb { border-radius: 10px; }
.term-detail { color: alpha(#cfe9dd, 0.55); }
.term expander title { min-height: 0; padding: 0; }
.drop-hint { background-color: alpha(#7a5cf0, 0.14); }
"""


def token():
    try:
        with open(TOKEN_PATH) as f:
            return f.read().strip()
    except OSError:
        return ""


def api(method, path, payload=None, base=API, timeout=10):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"X-Argon-Token": token(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def voice(path, payload=None, timeout=10):
    return api("POST", path, payload, base=VOICE_API, timeout=timeout)


def load_settings():
    try:
        with open(SETTINGS_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        with open(SETTINGS_PATH, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def in_thread(fn, done):
    """Ejecuta fn() fuera de la interfaz y entrega (resultado, error) a done() en el hilo de GTK."""
    def work():
        try:
            res, err = fn(), None
        except (urllib.error.URLError, OSError, ValueError) as e:
            res, err = None, e
        GLib.idle_add(lambda: done(res, err) and False)
    threading.Thread(target=work, daemon=True).start()


def label(text, css=None, wrap=True, select=False, xalign=0.0, markup=False):
    w = Gtk.Label(wrap=wrap, xalign=xalign, selectable=select)
    if markup:
        w.set_markup(text)
    else:
        w.set_text(text)
    w.set_wrap_mode(2)  # palabra o carácter
    if css:
        for c in css.split():
            w.add_css_class(c)
    return w


def md(text):
    """Markdown mínimo a Pango: **negrita**, `código`, # títulos y viñetas."""
    out = []
    for line in GLib.markup_escape_text(text.strip()).split("\n"):
        m = re.match(r"^#{1,4}\s+(.*)", line)
        if m:
            line = f"<b>{m.group(1)}</b>"
        line = re.sub(r"^(\s*)[-*]\s+", r"\1• ", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"`([^`]+)`", r"<tt>\1</tt>", line)
        out.append(line)
    return "\n".join(out)


def clip(text, limit=6000):
    """Recorta un texto enorme para la pantalla: el principio y el final, con lo omitido contado."""
    if len(text) <= limit:
        return text
    head, tail = limit // 3, limit - limit // 3
    return f"{text[:head]}\n\n… ({len(text) - limit:,} caracteres omitidos) …\n\n{text[-tail:]}".replace(",", ".")


def md_label(text, css=None):
    """Etiqueta con el markdown de md(); si Pango no acepta el resultado, va como texto plano."""
    markup = md(text)
    try:
        Pango.parse_markup(markup, -1, "\0")
    except GLib.Error:
        return label(text.strip(), css, select=True)
    return label(markup, css, select=True, markup=True)


_thumbs = {}


def thumbnail(path):
    """Miniatura de una imagen (en caché: la conversación se redibuja varias veces por segundo)."""
    if path not in _thumbs:
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 280, 200, True)
            _thumbs[path] = Gdk.Texture.new_for_pixbuf(pix)
        except GLib.Error:
            _thumbs[path] = None
    return _thumbs[path]


def open_path(path):
    try:
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
    except GLib.Error:
        pass


def stash(src):
    """Copia un adjunto a la carpeta de ARGON, para que quede con el historial aunque muevas el original."""
    folder = os.path.join(ATTACH_DIR, time.strftime("%Y%m%d-%H%M%S-") + f"{random.randrange(1 << 16):04x}")
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, os.path.basename(src))
    shutil.copy2(src, dest)
    return dest


class ArgonWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="ARGON", default_width=1040, default_height=720)
        self.set_hide_on_close(True)  # cerrar solo oculta: el historial y el trabajo siguen
        self.items = {}
        self.threads = {}
        self.rows = {}
        self.selected = None
        self.shown_key = None
        self.daemon_ok = True
        self.settings = load_settings()
        self.listening = False
        self.voice_ids = set()     # pedidos hechos hablando: ARGON contesta en voz alta
        self.spoken = {}           # id -> último estado que ya se leyó en voz alta
        self.busy_label = None
        self.busy_word = random.choice(BUSY_WORDS)
        self.word_tick = 0
        self.busy_item = None
        self.attachments = []
        self.expanded = {}         # qué razonamientos y detalles abriste (sobreviven a cada redibujo)

        # Barra lateral: historial.
        self.history = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.history.add_css_class("navigation-sidebar")
        self.history.connect("row-selected", self.on_row_selected)
        side_scroll = Gtk.ScrolledWindow(vexpand=True, child=self.history)
        new_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Nuevo pedido (Ctrl+N)")
        new_btn.connect("clicked", lambda *_: self.new_request())
        side_header = Adw.HeaderBar(title_widget=Adw.WindowTitle(title="Historial"))
        side_header.pack_start(new_btn)
        side = Adw.ToolbarView(content=side_scroll)
        side.add_top_bar(side_header)

        # Contenido: conversación del pedido elegido + caja para escribir.
        self.orb = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN)
        self.orb.set_size_request(30, 30)
        self.frames = [Gdk.Texture.new_from_filename(os.path.join(FRAMES_DIR, f))
                       for f in sorted(os.listdir(FRAMES_DIR)) if f.startswith("orb-")] if os.path.isdir(FRAMES_DIR) else []
        if self.frames:
            self.orb.set_paintable(self.frames[0])
        self.frame_i = 0
        title_box = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        title_box.append(self.orb)
        title_box.append(label("A R G O N", "argon-title title-3", wrap=False))
        header = Adw.HeaderBar(title_widget=title_box)
        self.split_btn = Gtk.ToggleButton(icon_name="sidebar-show-symbolic", active=True, tooltip_text="Historial")
        header.pack_start(self.split_btn)
        self.speaker = Gtk.ToggleButton(icon_name="audio-volume-high-symbolic",
                                        active=self.settings.get("speak", True),
                                        tooltip_text="ARGON contesta en voz alta cuando le hablas")
        self.speaker.connect("toggled", self.on_speaker)
        header.pack_end(self.speaker)

        self.conv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                            margin_top=18, margin_bottom=18, margin_start=22, margin_end=22)
        self.conv_scroll = Gtk.ScrolledWindow(vexpand=True, child=Adw.Clamp(maximum_size=820, child=self.conv))

        self.entry = Gtk.Entry(hexpand=True, placeholder_text="Pídele algo a ARGON…  (Enter para enviar)")
        self.entry.connect("activate", lambda *_: self.send())
        # Un solo botón: Enviar, que se vuelve Detener mientras la conversación elegida trabaja.
        self.send_btn = Gtk.Button()
        self.send_btn.add_css_class("circular")
        self.send_btn.connect("clicked", lambda *_: self.stop_current() if self.stopping else self.send())
        self.stopping = None
        self.set_send_mode(False)
        self.mic = Gtk.Button(icon_name="audio-input-microphone-symbolic", tooltip_text="Hablarle a ARGON (Ctrl+M)")
        self.mic.add_css_class("circular")
        self.mic.connect("clicked", lambda *_: self.toggle_listen())
        clip = Gtk.Button(icon_name="mail-attachment-symbolic",
                          tooltip_text="Adjuntar fotos o documentos (o arrástralos, o pega con Ctrl+V)")
        clip.add_css_class("circular")
        clip.connect("clicked", lambda *_: self.pick_files())
        self.chips = Gtk.Box(spacing=6, visible=False, margin_start=4)
        line = Gtk.Box(spacing=8)
        line.append(clip)
        line.append(self.mic)
        line.append(self.entry)
        line.append(self.send_btn)
        composer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        composer.add_css_class("composer")
        composer.append(self.chips)
        composer.append(line)

        content = Adw.ToolbarView(content=self.conv_scroll)
        content.add_top_bar(header)
        content.add_bottom_bar(Adw.Clamp(maximum_size=820, child=composer))

        self.split = Adw.OverlaySplitView(sidebar=side, content=content, sidebar_width_fraction=0.3,
                                          max_sidebar_width=340, min_sidebar_width=240)
        self.split_btn.bind_property("active", self.split, "show-sidebar",
                                     GObjectBinding.SYNC_CREATE | GObjectBinding.BIDIRECTIONAL)
        self.toast = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toast)

        keys = Gtk.ShortcutController()
        keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string("<Control>n"),
                                       action=Gtk.CallbackAction.new(lambda *_: self.new_request() or True)))
        keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string("<Control>period"),
                                       action=Gtk.CallbackAction.new(lambda *_: self.stop_current() or True)))
        keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string("<Control>m"),
                                       action=Gtk.CallbackAction.new(lambda *_: self.toggle_listen() or True)))
        keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string("Escape"),
                                       action=Gtk.CallbackAction.new(lambda *_: self.set_visible(False) or True)))
        self.add_controller(keys)

        # Ctrl+V con una imagen en el portapapeles la adjunta; el texto se pega normal.
        paste = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        paste.connect("key-pressed", self.on_key)
        self.add_controller(paste)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self.on_drop)
        drop.connect("enter", self.on_drag_enter)
        drop.connect("leave", lambda *_: self.conv_scroll.remove_css_class("drop-hint"))
        self.add_controller(drop)

        self.show_empty()
        self.refresh()
        self.tick_n = 0
        GLib.timeout_add(500, self.tick)
        GLib.timeout_add(100, self.animate)

    # --- Datos ---------------------------------------------------------------

    def tick(self):
        # Con algo en curso se refresca dos veces por segundo; si no, cada 2 s. Oculta, cada 3 s (para la voz).
        self.tick_n += 1
        busy = any(i["status"] in ACTIVE for i in self.items.values())
        every = (1 if busy else 4) if self.is_visible() else 6
        if self.tick_n % every == 0:
            self.refresh()
        return True

    def refresh(self):
        in_thread(lambda: api("GET", "/requests?limit=200"), self.on_list)

    def on_list(self, items, err):
        if err:
            if self.daemon_ok:
                self.daemon_ok = False
                self.toast.add_toast(Adw.Toast(title="argond no responde: revisa el servicio ARGON.", timeout=6))
            return
        self.daemon_ok = True
        self.items = {i["id"]: i for i in items}
        # Un hilo = una conversación. El historial muestra hilos, el más reciente arriba.
        self.threads = {}
        for item in sorted(items, key=lambda i: i["id"]):
            self.threads.setdefault(item.get("thread") or item["id"], []).append(item)
        order = sorted(self.threads, key=lambda t: self.threads[t][-1]["id"], reverse=True)
        for pos, tid in enumerate(order):
            row = self.rows.get(tid)
            if row is None:
                row = self.make_row(tid)
                self.rows[tid] = row
                self.history.insert(row, pos)
            elif row.get_index() != pos:
                selected = self.history.get_selected_row() is row
                self.history.remove(row)
                self.history.insert(row, pos)
                if selected:
                    self.history.select_row(row)
            self.update_row(row, self.threads[tid])
        for tid in [t for t in self.rows if t not in self.threads]:
            self.history.remove(self.rows.pop(tid))
        if self.selected in self.threads:
            self.show_thread(self.selected)
        self.update_stop()
        for rid in list(self.voice_ids):
            if rid in self.items:
                self.maybe_speak(self.items[rid])

    def make_row(self, tid):
        row = Adw.ActionRow(title_lines=1, subtitle_lines=1)
        row.dot = label("●", wrap=False)
        row.add_prefix(row.dot)
        row.rid = tid
        return row

    def update_row(self, row, turns):
        first, last = turns[0], turns[-1]
        row.set_title(GLib.markup_escape_text(first["text"]))
        text, css = STATUS_STYLE.get(last["status"], (last["status"], "st-off"))
        when = time.strftime("%d/%m %H:%M", time.localtime(last["created"]))
        count = f" · {len(turns)} mensajes" if len(turns) > 1 else ""
        row.set_subtitle(f"{text} · {when}{count}")
        for c in ("st-ok", "st-bad", "st-wait", "st-busy", "st-off"):
            row.dot.remove_css_class(c)
        row.dot.add_css_class(css)

    def current_turn(self):
        turns = self.threads.get(self.selected) if self.selected else None
        return turns[-1] if turns else None

    # --- Conversación ----------------------------------------------------------

    def on_row_selected(self, box, row):
        if row is None:
            return
        if self.selected != row.rid:
            self.selected = row.rid
            self.shown_key = None
            self.show_thread(row.rid)
            self.update_stop()
            GLib.idle_add(self.scroll_bottom)
        self.entry.set_placeholder_text("Sigue la conversación…  (Ctrl+N para un tema nuevo)")

    def clear(self):
        while (child := self.conv.get_first_child()) is not None:
            self.conv.remove(child)

    def show_empty(self):
        self.clear()
        self.conv.append(label("Escribe abajo lo que necesitas.", "title-2", xalign=0.5))
        self.conv.append(label(
            "ARGON hace lo simple en el escritorio, delega a Black Hat lo que requiere trabajo en este Linux "
            "y le encarga a tu coordinador lo de la flota (si lo configuras). Lo delicado te pide permiso aquí mismo, y puedes cerrar la "
            "ventana: el trabajo sigue y queda en el historial.", "dim-label", xalign=0.5))

    def show_thread(self, tid):
        turns = self.threads[tid]
        key = tuple((t["id"], t["updated"]) for t in turns)
        if key == self.shown_key:
            return
        new = self.shown_key is None
        self.shown_key = key
        # Si estabas abajo, sigue lo nuevo; si subiste a leer, te deja donde estabas.
        adj = self.conv_scroll.get_vadjustment()
        stick = new or adj.get_value() >= adj.get_upper() - adj.get_page_size() - 60
        saved = adj.get_value()
        self.clear()
        self.busy_label = None
        for n, item in enumerate(turns):
            self.show_turn(item, n == 0)
        GLib.idle_add(self.scroll_bottom if stick else (lambda: adj.set_value(saved) or False))

    def show_turn(self, item, first):
        user = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.END,
                       margin_top=0 if first else 14)
        if item.get("files"):
            user.append(self.files_box(item["files"]))
        user.append(label(item["text"], "bubble-user", select=True))
        self.conv.append(user)

        if item.get("events"):
            self.show_events(item)
        else:  # turnos del ARGON anterior: respuesta + pasos del plan
            if item.get("reply"):
                self.conv.append(self.text_bubble(item["reply"]))
            for i, step in enumerate(item.get("steps") or [], 1):
                self.conv.append(self.step_card(i, step))

        status_text, status_css = STATUS_STYLE.get(item["status"], (item["status"], "st-off"))
        foot = Gtk.Box()
        if item["status"] in ("pensando", "ejecutando"):
            self.busy_label = Gtk.Label(xalign=0, use_markup=True, wrap=True, hexpand=True)
            self.busy_label.add_css_class("busy-line")
            self.busy_item = item
            self.update_busy()
            foot.append(self.busy_label)
        else:
            foot.append(label(status_text, f"caption {status_css}"))
            foot.get_last_child().set_hexpand(True)
        self.conv.append(foot)
        if item.get("error"):
            self.conv.append(label(item["error"], "caption st-bad", select=True))

    def show_events(self, item):
        """Los events del turno, en orden: razonamiento, texto, comandos (agrupados en una terminal), plan y permisos."""
        live = item["status"] in BUSY
        events = item["events"]
        term = None
        for n, ev in enumerate(events):
            t = ev.get("t")
            if t != "tool":
                term = None
            text = (ev.get("text") or "").strip()
            if t in ("text", "local") and text:
                self.conv.append(self.text_bubble(text))
            elif t == "thought" and text:
                self.conv.append(self.thought(f'{item["id"]}:{n}', text, live and n == len(events) - 1))
            elif t == "tool":
                if term is None:
                    term = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
                    term.add_css_class("term")
                    self.conv.append(term)
                self.tool_lines(term, item["id"], ev)
            elif t == "plan" and ev.get("entries"):
                self.conv.append(self.plan_card(ev["entries"]))
            elif t in ("permission", "confirm"):
                self.conv.append(self.permission_card(item, ev, live))
            elif t == "note" and text:
                self.conv.append(label(text, "caption dim-label"))

    def text_bubble(self, text):
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.START)
        bubble.add_css_class("bubble-argon")
        bubble.append(md_label(clip(text, 20000)))
        return bubble

    def expander(self, key, title, child, default=False, css=None):
        exp = Gtk.Expander(label=title, expanded=self.expanded.get(key, default), child=child)
        if css:
            exp.add_css_class(css)
        exp.connect("notify::expanded", lambda e, _p: self.expanded.__setitem__(key, e.get_expanded()))
        return exp

    def thought(self, key, text, live):
        # Mientras Black Hat razona se ve abierto; después queda plegado (salvo que lo abras tú).
        words = len(text.split())
        return self.expander(key, f"Razonamiento · {words} palabras", label(clip(text), "thought", select=True),
                             default=live, css="thought")

    def tool_lines(self, term, rid, ev):
        mark, css = TOOL_STYLE.get(ev.get("status"), ("○", "st-off"))
        title = ev.get("title") or ev.get("kind") or "herramienta"
        inp = (ev.get("input") or "").strip()
        head = Gtk.Box(spacing=6)
        head.append(label(mark, css, wrap=False))
        if inp.startswith("$ ") and "\n" not in inp:  # un comando de terminal: se muestra tal cual
            head.append(label(inp, "term-cmd", select=True))
            inp = ""
        else:
            head.append(label(title, "term-tool", select=True))
        head.get_last_child().set_hexpand(True)
        term.append(head)
        if inp and inp != title:
            code = re.sub(r"^```\w*\n|\n?```$", "", re.sub(r"\n\n```", "\n```", inp), flags=re.M).strip()
            term.append(self.expander(f'{rid}:{ev.get("id")}:in', "ver detalle",
                                      label(code, "term-detail", select=True), css="term-detail"))
        out = (ev.get("output") or "").strip()
        if out:
            term.append(label("  ⎿ " + out.replace("\n", "\n    "),
                              "term-err" if ev.get("status") == "failed" else "term-ok", select=True))

    def plan_card(self, entries):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("step-card")
        card.append(label("Plan", "heading"))
        for e in entries:
            status = e.get("status", "pending")
            css = {"completed": "st-ok", "in_progress": "st-busy"}.get(status, "st-off")
            row = Gtk.Box(spacing=8)
            row.append(label(PLAN_MARK.get(status, "○"), css, wrap=False))
            row.append(label(e.get("text", "")))
            card.append(row)
        return card

    def permission_card(self, item, ev, live):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("perm-card")
        card.append(label(ev.get("title") or "Black Hat pide permiso", "heading", select=True))
        if ev.get("detail"):
            card.append(label(ev["detail"], "brief", select=True))
        options = ev.get("options") or []
        answer = ev.get("answer")
        if answer is None and live:
            buttons = Adw.WrapBox(child_spacing=8, line_spacing=8, halign=Gtk.Align.END)
            first_allow = True
            for opt in options:
                btn = Gtk.Button(label=opt.get("name") or opt.get("id"))
                if opt.get("kind", "").startswith("allow"):
                    if first_allow:
                        btn.add_css_class("suggested-action")
                    first_allow = False
                elif opt.get("kind", "").startswith(("reject", "deny")):
                    btn.add_css_class("destructive-action")
                btn.connect("clicked", lambda _b, o=opt["id"]: self.answer(item["id"], ev["id"], o, buttons))
                buttons.append(btn)
            card.append(buttons)
        else:
            chosen = next((o for o in options if o.get("id") == answer), None)
            if chosen:
                ok = chosen.get("kind", "").startswith("allow")
                card.append(label(f'Elegiste: {chosen.get("name") or chosen["id"]}',
                                  f'caption {"st-ok" if ok else "st-bad"}'))
            else:
                card.append(label("Sin respuesta: se rechazó solo.", "caption st-off"))
        return card

    def files_box(self, files):
        box = Adw.WrapBox(child_spacing=6, line_spacing=6, halign=Gtk.Align.END)
        for path in files:
            btn = Gtk.Button(tooltip_text=path, valign=Gtk.Align.CENTER)
            btn.add_css_class("flat")
            tex = thumbnail(path) if path.lower().endswith(IMAGE_EXT) and os.path.isfile(path) else None
            if tex:
                pic = Gtk.Picture(paintable=tex, can_shrink=True, content_fit=Gtk.ContentFit.COVER)
                pic.set_size_request(140, 100)
                pic.add_css_class("thumb")
                btn.set_child(pic)
            else:
                chip = Gtk.Box(spacing=6)
                chip.add_css_class("attach-chip")
                chip.append(Gtk.Image(icon_name="text-x-generic-symbolic"))
                chip.append(label(os.path.basename(path)[:40], "caption", wrap=False))
                btn.set_child(chip)
            btn.connect("clicked", lambda _b, p=path: open_path(p))
            box.append(btn)
        return box

    def scroll_bottom(self):
        adj = self.conv_scroll.get_vadjustment()
        adj.set_value(adj.get_upper())
        return False

    def update_busy(self):
        item = self.busy_item
        secs = int(time.time() - item["created"])
        when = f"{secs} s" if secs < 60 else f"{secs // 60} min {secs % 60:02d} s"
        events = item.get("events") or []
        doing = "Black Hat se prepara"
        tool = next((e for e in reversed(events) if e.get("t") == "tool"
                     and e.get("status") in ("pending", "in_progress")), None)
        if tool:
            inp = (tool.get("input") or "").strip()
            doing = inp if inp.startswith("$ ") and "\n" not in inp else tool.get("title", "")
        elif events and events[-1].get("t") == "thought":
            doing = "razona"
        elif events and events[-1].get("t") == "text":
            doing = "escribe"
        elif item["status"] == "ejecutando":  # turnos del ARGON anterior
            cur = next((s for s in item.get("steps") or [] if s.get("status") == "en curso"), None)
            if cur:
                doing = TOOL_NAMES.get(cur["tool"], cur["tool"]) + ": " + cur["label"]
        spin = "✻✽✶✳✢·"[self.word_tick % 6]
        self.busy_label.set_markup(
            f"{spin} {GLib.markup_escape_text(self.busy_word)}… "
            f"<span size='small' alpha='60%'>({when} · {GLib.markup_escape_text(doing[:90])})</span>")

    def step_card(self, i, step):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("step-card")
        top = Gtk.Box(spacing=10)
        mark, css = STEP_STYLE.get(step.get("status", "pendiente"), ("○", "st-off"))
        top.append(label(mark, f"heading {css}", wrap=False))
        top.append(label(f"{i}. {step['label']}", "heading"))
        top.get_last_child().set_hexpand(True)
        top.append(label(TOOL_NAMES.get(step["tool"], step["tool"]), "tool-chip dim-label", wrap=False))
        card.append(top)
        if step["tool"] == "delegar_black_hat":
            card.append(label("Tarea: " + step["args"].get("tarea", ""), "dim-label", select=True))
        if step.get("log"):
            term = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            term.add_css_class("term")
            for e in step["log"][-40:]:
                if e["t"] == "cmd":
                    term.append(label("$ " + e["text"], "term-cmd", select=True))
                elif e["t"] == "tool":
                    term.append(label(f'● {e["name"]}  {e["text"]}', "term-tool", select=True))
                elif e["text"]:
                    ms = f'  ({e["ms"] / 1000:.1f} s)' if e.get("ms") else ""
                    term.append(label("  ⎿ " + e["text"].replace("\n", "\n    ") + ms,
                                      "term-err" if e["t"] == "err" else "term-ok", select=True))
            card.append(term)
        if step.get("output"):
            card.append(label(step["output"], None if step.get("log") else "output", select=True))
        return card

    def act(self, rid, action):
        in_thread(lambda: api("POST", f"/requests/{rid}/{action}"), lambda r, e: self.refresh())

    def answer(self, rid, eid, option, buttons=None):
        """Responde una tarjeta de permiso o de confirmación (POST /requests/<id>/answer)."""
        if buttons is not None:
            buttons.set_sensitive(False)

        def done(res, err):
            if err:
                self.toast.add_toast(Adw.Toast(title="Ese permiso ya no estaba esperando (se respondió o venció).",
                                               timeout=5))
            self.refresh()
        in_thread(lambda: api("POST", f"/requests/{rid}/answer", {"event": eid, "option": option}), done)

    def pending_question(self, item):
        """La tarjeta de permiso o confirmación que el turno está esperando, si hay una."""
        if not item or item["status"] not in BUSY:
            return None
        return next((e for e in item.get("events") or [] if e.get("t") in ("permission", "confirm")
                     and e.get("answer") is None), None)

    def set_send_mode(self, stop):
        if self.stopping == stop:
            return
        self.stopping = stop
        btn = self.send_btn
        btn.remove_css_class("destructive-action" if not stop else "suggested-action")
        btn.add_css_class("destructive-action" if stop else "suggested-action")
        btn.set_icon_name("media-playback-stop-symbolic" if stop else "go-up-symbolic")
        btn.set_tooltip_text("Detener a Black Hat (Ctrl+.)" if stop else "Enviar")
        btn.set_sensitive(True)

    def update_stop(self):
        turn = self.current_turn()
        self.set_send_mode(bool(turn) and turn["status"] in BUSY)

    def stop_current(self):
        turn = self.current_turn()
        if turn and turn["status"] in BUSY:
            self.send_btn.set_sensitive(False)
            in_thread(lambda: api("POST", f'/requests/{turn["id"]}/cancel'),
                      lambda r, e: (self.send_btn.set_sensitive(True), self.refresh()))

    def new_request(self):
        self.history.unselect_all()
        self.selected = None
        self.shown_key = None
        self.show_empty()
        self.update_stop()
        self.entry.set_placeholder_text("Pídele algo a ARGON…  (Enter para enviar)")
        self.entry.grab_focus()

    def send(self, by_voice=False):
        text = self.entry.get_text().strip()
        files = list(self.attachments)
        if not text and not files:
            return
        self.entry.set_text("")
        self.attachments = []
        self.render_chips()

        thread = self.selected  # None = tema nuevo

        def done(res, err):
            if err:
                self.toast.add_toast(Adw.Toast(title="No pude enviar el pedido: argond no responde.", timeout=6))
                self.entry.set_text(text)
                self.attachments = files + self.attachments
                self.render_chips()
                return
            self.selected = thread or res["id"]
            if by_voice:
                self.voice_ids.add(res["id"])
            self.shown_key = None
            self.refresh()
            GLib.timeout_add(400, lambda: self.select_row(self.selected) and False)
        payload = {"text": text}
        if thread is not None:
            payload["thread"] = thread
        if files:
            payload["files"] = files  # rutas ya copiadas a ~/.local/share/argon/adjuntos
        in_thread(lambda: api("POST", "/requests", payload), done)

    def select_row(self, rid):
        row = self.rows.get(rid)
        if row:
            self.history.select_row(row)
        return False

    # --- Adjuntos ------------------------------------------------------------

    def pick_files(self):
        dialog = Gtk.FileDialog(title="Adjuntar a ARGON")
        dialog.open_multiple(self, None, self.on_picked)

    def on_picked(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return  # cancelado
        for i in range(files.get_n_items()):
            path = files.get_item(i).get_path()
            if path:
                self.add_attachment(path)

    def on_drag_enter(self, *_):
        self.conv_scroll.add_css_class("drop-hint")
        return Gdk.DragAction.COPY

    def on_drop(self, target, value, x, y):
        self.conv_scroll.remove_css_class("drop-hint")
        for f in value.get_files():
            if f.get_path():
                self.add_attachment(f.get_path())
        return True

    def on_key(self, ctrl, keyval, keycode, state):
        if not (state & Gdk.ModifierType.CONTROL_MASK) or keyval not in (Gdk.KEY_v, Gdk.KEY_V):
            return False
        clipboard = self.get_clipboard()
        if not clipboard.get_formats().contain_gtype(Gdk.Texture.__gtype__):
            return False
        clipboard.read_texture_async(None, self.on_pasted_image)
        return True

    def on_pasted_image(self, clipboard, result):
        try:
            texture = clipboard.read_texture_finish(result)
        except GLib.Error:
            return
        os.makedirs(ATTACH_DIR, exist_ok=True)
        path = os.path.join(ATTACH_DIR, time.strftime("pegado-%Y%m%d-%H%M%S.png"))
        texture.save_to_png(path)
        self.add_attachment(path, copy=False)

    def add_attachment(self, path, copy=True):
        if not os.path.isfile(path):
            self.toast.add_toast(Adw.Toast(title="Por ahora solo archivos, no carpetas.", timeout=3))
            return
        try:
            path = stash(path) if copy else path
        except OSError as e:
            self.toast.add_toast(Adw.Toast(title=f"No pude adjuntar: {e}", timeout=4))
            return
        self.attachments.append(path)
        self.render_chips()
        self.entry.grab_focus()

    def render_chips(self):
        while (child := self.chips.get_first_child()) is not None:
            self.chips.remove(child)
        for path in self.attachments:
            chip = Gtk.Box(spacing=4)
            chip.add_css_class("attach-chip")
            icon = "image-x-generic-symbolic" if path.lower().endswith(IMAGE_EXT) else "text-x-generic-symbolic"
            chip.append(Gtk.Image(icon_name=icon))
            chip.append(label(os.path.basename(path)[:32], "caption", wrap=False))
            x = Gtk.Button(icon_name="window-close-symbolic", tooltip_text="Quitar")
            x.add_css_class("flat")
            x.add_css_class("circular")
            x.connect("clicked", lambda _b, p=path: self.remove_attachment(p))
            chip.append(x)
            self.chips.append(chip)
        self.chips.set_visible(bool(self.attachments))

    def remove_attachment(self, path):
        self.attachments = [p for p in self.attachments if p != path]
        self.render_chips()

    # --- Voz ----------------------------------------------------------------

    def on_speaker(self, btn):
        self.settings["speak"] = btn.get_active()
        save_settings(self.settings)
        if not btn.get_active():
            in_thread(lambda: voice("/speak/stop"), lambda r, e: None)

    def toggle_listen(self):
        if self.listening:
            in_thread(lambda: voice("/listen/stop"), lambda r, e: None)
            return
        self.listening = True
        self.mic.add_css_class("mic-on")
        self.mic.set_icon_name("media-record-symbolic")
        self.entry.set_placeholder_text("Te escucho…  (habla y haz una pausa; clic de nuevo para cortar)")
        in_thread(lambda: voice("/listen", timeout=90), self.on_heard)

    def on_heard(self, res, err):
        self.listening = False
        self.mic.remove_css_class("mic-on")
        self.mic.set_icon_name("audio-input-microphone-symbolic")
        self.entry.set_placeholder_text("Sigue la conversación…  (Ctrl+N para un tema nuevo)" if self.selected
                                        else "Pídele algo a ARGON…  (Enter para enviar)")
        if err:
            self.toast.add_toast(Adw.Toast(title="El servicio de voz no responde (argon-voz).", timeout=6))
            return
        text = (res or {}).get("text", "").strip()
        if not text:
            self.toast.add_toast(Adw.Toast(title="No te escuché. Prueba de nuevo.", timeout=3))
            return
        # Si hay un permiso esperando, un "sí, dale" lo permite (una vez) y un "no" lo rechaza.
        words = text.lower().strip(" .,!¡¿?").replace(",", " ").split()
        waiting = self.current_turn()
        question = self.pending_question(waiting)
        if question and 0 < len(words) <= 4:
            word = words[0].strip(".,!")
            kinds = ("allow_once", "allow") if word in YES_WORDS else ("reject_once", "reject", "deny")
            if word in YES_WORDS or word in NO_WORDS:
                opts = question.get("options") or []
                opt = next((o for k in kinds for o in opts if o.get("kind", "").startswith(k)), None)
                if opt:
                    self.voice_ids.add(waiting["id"])
                    return self.answer(waiting["id"], question["id"], opt["id"])
        self.entry.set_text(text)
        self.send(by_voice=True)

    def maybe_speak(self, item):
        status = item["status"]
        question = self.pending_question(item)
        mark = f'permiso:{question["id"]}' if question else status
        if (status in BUSY and not question) or self.spoken.get(item["id"]) == mark:
            return
        self.spoken[item["id"]] = mark
        if question:
            text = "Necesito tu permiso: " + (question.get("title") or "") + ". ¿Lo permito?"
        elif status in ("respondido", "hecho"):
            outs = [s.get("output", "") for s in item.get("steps") or [] if s["tool"] == "delegar_black_hat"]
            text = outs[-1] if outs and outs[-1] else (item.get("reply") or "Listo.")
            self.voice_ids.discard(item["id"])
        elif status == "falló":
            text = "No pude. " + (item.get("error") or "")
            self.voice_ids.discard(item["id"])
        else:
            self.voice_ids.discard(item["id"])
            return
        if self.speaker.get_active() and text:
            in_thread(lambda: voice("/speak", {"text": text}), lambda r, e: None)

    # --- Orbe ---------------------------------------------------------------

    def animate(self):
        busy = any(i["status"] in ("pensando", "ejecutando") for i in self.items.values())
        if self.frames and self.is_visible():
            step = 2 if busy else 1
            self.frame_i = (self.frame_i + step) % len(self.frames)
            self.orb.set_paintable(self.frames[self.frame_i])
        # La línea "✻ Ionizando… (12 s · …)" se mueve sola; la palabra cambia cada ~4 s.
        if self.busy_label is not None and self.is_visible():
            self.word_tick += 1
            if self.word_tick % 40 == 0:
                self.busy_word = random.choice(BUSY_WORDS)
            if self.word_tick % 2 == 0:
                self.update_busy()
        return True



class ArgonApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.win = None
        toggle = Gio.SimpleAction.new("toggle", None)
        toggle.connect("activate", lambda *_: self.toggle())
        self.add_action(toggle)

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.hold()  # la app sigue viva con la ventana oculta: abrirla de nuevo es instantáneo

    def do_activate(self):
        if self.win is None:
            self.win = ArgonWindow(self)
        self.win.present()
        self.win.entry.grab_focus()

    def toggle(self):
        if self.win and self.win.is_visible() and self.win.is_active():
            self.win.set_visible(False)
        else:
            self.activate()


if __name__ == "__main__":
    sys.exit(ArgonApp().run(sys.argv))
