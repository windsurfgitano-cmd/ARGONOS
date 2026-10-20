#!/usr/bin/env python3
"""argond — el servicio de ARGON. Corre siempre (servicio de usuario de systemd).

ARGON es la cara de Black Hat (el agente Hermes de este equipo) en el escritorio. argond mantiene a Hermes
vivo en modo ACP (Agent Client Protocol): cada hilo de ARGON es una sesión de Black Hat, que escribe mientras
trabaja, muestra cada comando, pregunta cuando le falta algo y pide permiso antes de lo delicado. Lo
instantáneo del escritorio ("abre Firefox", "escritorio 2") se hace aquí mismo, sin pasar por el modelo.
Cerrar la ventana no detiene nada: todo queda en el historial (SQLite).

API local, solo en 127.0.0.1:8737, con la clave de ~/.local/share/argon/token (cabecera X-Argon-Token):
  POST /requests              {"text", "thread"?, "files"?: [rutas]}  -> {"id"}   (sin thread = hilo nuevo)
  GET  /requests?limit=50                                            -> [turno, ...] (más nuevo primero)
  GET  /requests/<id>                                                -> turno
  POST /requests/<id>/answer  {"event": id, "option": id}            -> responde un permiso o una confirmación
  POST /requests/<id>/cancel                                         -> detiene el turno
  POST /tools/call            {"thread", "name", "args"}             -> herramientas ARGON (las usa argon_mcp.py)
  GET  /status                                                       -> {"thinking", "running", "waiting", "hermes"}
"""
import json
import mimetypes
import os
import re
import secrets
import shlex
import sqlite3
import subprocess
import threading
import time
import urllib.request
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

HOST, PORT = "127.0.0.1", 8737
STRATA = "http://127.0.0.1:8080"
DATA = os.path.join(GLib.get_user_data_dir(), "argon")
DB_PATH = os.path.join(DATA, "argon.db")
TOKEN_PATH = os.path.join(DATA, "token")
ACP_LOG = os.path.join(DATA, "hermes-acp.log")
MCP_SCRIPT = os.path.join(DATA, "argon_mcp.py")
HOME = GLib.get_home_dir()

# Ajustes personales en ~/.config/argon/argon.json (ver config/argon.ejemplo.json). Sin ese archivo,
# ARGON funciona solo en este equipo: sin flota y sin encargos remotos.
CONFIG_PATH = os.path.join(GLib.get_user_config_dir(), "argon", "argon.json")


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


CONFIG = load_config()
USER_NAME = CONFIG.get("nombre") or GLib.get_real_name() or GLib.get_user_name()
HUB = CONFIG.get("hub") or {}
HUB_SSH = HUB.get("ssh", "")           # p. ej. "usuario@coordinador" (vía tailscale ssh)
HUB_NAME = HUB.get("nombre", "el coordinador")
HUB_ENDPOINT = HUB.get("endpoint", "hermes-bus-gateway")
SENDER = HUB.get("remitente", "argon")
PERMISSION_WAIT = 280      # Hermes se rinde a los 300 s (approvals.timeout); contestamos antes
CONFIRM_WAIT = 15 * 60     # encargos a la flota: te esperan 15 minutos
CONTEXT_TURNS = 8
LOOP_CHECK_EVERY = 400     # cada cuántos caracteres nuevos se revisa si Black Hat se quedó repitiendo

FOLDERS = {
    "Inicio": HOME,
    "Documentos": GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS),
    "Descargas": GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD),
    "Imágenes": GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES),
    "Música": GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC),
    "Vídeos": GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS),
    "Escritorio": GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP),
}
for _name, _path in (CONFIG.get("carpetas") or {}).items():
    FOLDERS[_name] = os.path.expanduser(_path)

OPTION_NAMES = {"allow_once": "Permitir una vez", "allow_session": "Permitir en esta conversación",
                "allow_always": "Permitir siempre", "deny": "Rechazar", "deny_always": "Rechazar siempre"}

INTRO = f"""[ARGON] {USER_NAME} te habla desde ARGON, la ventana de su escritorio (GNOME), y puede estar hablándote por voz.
- Responde en español, claro y breve. Mientras trabajas, cuenta en una línea qué vas a hacer.
- Si te falta un dato o hay una decisión que es suya, PREGÚNTALE y termina tu turno: su respuesta llega como el
  siguiente mensaje de esta misma conversación. No supongas lo que no sabes.
- Para el escritorio usa las herramientas argon_* (abrir apps o carpetas, cambiar de escritorio, modo foco).
"""
if HUB_SSH:
    INTRO += (f'- Para cualquier cosa de {HUB_NAME} o "la flota" usa argon_encargo_flota: '
              f"{USER_NAME} confirma antes del envío.\n")

_db_lock = threading.Lock()
_focus_timer = None
TOKEN = ""


# --- Historial ---------------------------------------------------------------

@contextmanager
def db():
    # "with sqlite3.connect()" solo confirma la transacción, no cierra: sin el close() se agotan los archivos.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    os.makedirs(DATA, exist_ok=True)
    with _db_lock, db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created REAL, updated REAL,
            text TEXT, reply TEXT, steps TEXT, status TEXT, error TEXT)""")
        cols = {r[1] for r in c.execute("PRAGMA table_info(requests)")}
        for col, kind in (("thread", "INTEGER"), ("files", "TEXT"), ("events", "TEXT"), ("kind", "TEXT")):
            if col not in cols:
                c.execute(f"ALTER TABLE requests ADD COLUMN {col} {kind}")
        c.execute("UPDATE requests SET thread=id WHERE thread IS NULL")
        c.execute("CREATE TABLE IF NOT EXISTS threads (id INTEGER PRIMARY KEY, session TEXT)")
        # Lo que quedó a medias si el servicio se reinició no sigue corriendo.
        c.execute("UPDATE requests SET status='interrumpido', updated=? WHERE status IN "
                  "('pensando','ejecutando','necesita tu permiso','esperando confirmación')", (time.time(),))
    if not os.path.exists(TOKEN_PATH):
        fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))


def save(rid, **fields):
    fields["updated"] = time.time()
    for k in ("steps", "events", "files"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    cols = ", ".join(f"{k}=?" for k in fields)
    with _db_lock, db() as c:
        c.execute(f"UPDATE requests SET {cols} WHERE id=?", (*fields.values(), rid))


def load(rid):
    with _db_lock, db() as c:
        row = c.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    return row_dict(row) if row else None


def row_dict(row):
    d = dict(row)
    for k in ("steps", "events", "files"):
        d[k] = json.loads(d.get(k) or "[]")
    return d


def thread_session(thread):
    with _db_lock, db() as c:
        row = c.execute("SELECT session FROM threads WHERE id=?", (thread,)).fetchone()
    return row[0] if row else None


def set_thread_session(thread, session):
    with _db_lock, db() as c:
        c.execute("INSERT INTO threads (id, session) VALUES (?, ?) "
                  "ON CONFLICT(id) DO UPDATE SET session=excluded.session", (thread, session))


def earlier_turns(rid):
    with _db_lock, db() as c:
        rows = c.execute("SELECT * FROM requests WHERE thread=(SELECT thread FROM requests WHERE id=?) AND id<? "
                         "ORDER BY id DESC LIMIT ?", (rid, rid, CONTEXT_TURNS)).fetchall()
    return [row_dict(r) for r in reversed(rows)]


def notify(title, body=""):
    try:
        subprocess.Popen(["notify-send", "-a", "ARGON", "-i", "argon", title, body[:200]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


# --- Un turno en curso ------------------------------------------------------

class Turn:
    """Lo que Black Hat va haciendo en un turno; se guarda en el historial a medida que pasa."""

    def __init__(self, rid):
        self.rid = rid
        self.events = []
        self.lock = threading.RLock()
        self.waiters = {}       # id de evento -> (threading.Event, [respuesta])
        self.last_save = 0.0
        self.status = "pensando"
        self.looped = False     # se quedó repitiendo lo mismo y argond lo cortó
        self.checked = 0        # largo del texto la última vez que se buscó repetición

    def flush(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_save < 0.3:
            return
        self.last_save = now
        with self.lock:
            events = json.loads(json.dumps(self.events))
            status = self.status
        save(self.rid, events=events, reply=self.reply_text(), status=status)

    def reply_text(self):
        with self.lock:
            return "".join(e["text"] for e in self.events if e["t"] == "text").strip()

    def add_chunk(self, kind, text):
        with self.lock:
            if self.looped:
                return  # ya se cortó: lo que siga llegando antes de que Hermes pare se descarta
            if self.events and self.events[-1]["t"] == kind:
                self.events[-1]["text"] += text
            else:
                self.events.append({"t": kind, "text": text})
                self.checked = 0
            ev = self.events[-1]
            if len(ev["text"]) - self.checked >= LOOP_CHECK_EVERY:
                self.checked = len(ev["text"])
                cut = repetition_start(ev["text"])
                if cut is not None:
                    self.looped = True
                    ev["text"] = ev["text"][:cut].rstrip() + "\n[… aquí se quedó repitiendo lo mismo: ARGON lo cortó]"
        if self.looped:
            self.flush(force=True)
            threading.Thread(target=HERMES.cancel, args=(self.rid,), daemon=True).start()
        else:
            self.flush()

    def find(self, eid):
        return next((e for e in self.events if e.get("id") == eid), None)

    def ask(self, event, wait):
        """Agrega una pregunta con botones (permiso o confirmación) y espera la respuesta del usuario."""
        done, answer = threading.Event(), [None]
        with self.lock:
            self.events.append(event)
            self.waiters[event["id"]] = (done, answer)
            self.status = "necesita tu permiso"
        self.flush(force=True)
        notify("ARGON necesita tu permiso", event.get("title", ""))
        done.wait(wait)
        with self.lock:
            self.waiters.pop(event["id"], None)
            event["answer"] = answer[0] or "sin respuesta"
            if not self.waiters and self.status == "necesita tu permiso":
                self.status = "pensando"
        self.flush(force=True)
        return answer[0]

    def answer(self, eid, option):
        with self.lock:
            waiter = self.waiters.get(eid)
        if not waiter:
            return False
        waiter[1][0] = option
        waiter[0].set()
        return True

    def release_all(self):
        with self.lock:
            waiters = list(self.waiters.values())
        for done, _ in waiters:
            done.set()


# --- Black Hat por ACP ------------------------------------------------------

class Hermes:
    """Un proceso `hermes acp` siempre vivo, hablado por JSON-RPC (una línea por mensaje)."""

    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()          # arrancar / escribir
        self.start_lock = threading.Lock()
        self.next_id = 0
        self.pending = {}                     # id de llamada -> (Event, [respuesta])
        self.loaded = set()                   # sesiones abiertas en este proceso
        self.replaying = set()                # sesiones cargándose: su historial repetido se ignora
        self.turns = {}                       # sesión -> Turn en curso
        self.thread_locks = {}

    @property
    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def ensure(self):
        with self.start_lock:
            if self.alive:
                return
            self.loaded.clear()
            log = open(ACP_LOG, "a")
            with self.lock:
                self.proc = subprocess.Popen(["hermes", "acp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=log, text=True, bufsize=1, cwd=HOME)
            threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
            self.call("initialize", {"protocolVersion": 1, "clientCapabilities": {
                "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}, timeout=180)

    def _write(self, msg):
        with self.lock:
            self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def call(self, method, params, timeout=None):
        with self.lock:
            self.next_id += 1
            cid = self.next_id
            done, box = threading.Event(), [None]
            self.pending[cid] = (done, box)
        self._write({"jsonrpc": "2.0", "id": cid, "method": method, "params": params})
        if not done.wait(timeout):
            self.pending.pop(cid, None)
            raise RuntimeError(f"Hermes no respondió a {method}.")
        msg = box[0]
        if msg.get("dead"):
            raise RuntimeError("Hermes se cerró en medio del trabajo.")
        if "error" in msg:
            raise RuntimeError(msg["error"].get("message") or str(msg["error"]))
        return msg.get("result") or {}

    def send_notification(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _read(self, proc):
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue  # avisos del bus y otras líneas sueltas
            if not isinstance(msg, dict):
                continue
            if "method" not in msg:
                waiter = self.pending.pop(msg.get("id"), None)
                if waiter:
                    waiter[1][0] = msg
                    waiter[0].set()
            elif msg["method"] == "session/update":
                try:
                    self._on_update(msg.get("params") or {})
                except Exception as e:  # noqa: BLE001 — un evento raro no debe tumbar la lectura
                    print("evento ignorado:", e, flush=True)
            elif msg["method"] == "session/request_permission" and "id" in msg:
                threading.Thread(target=self._on_permission, args=(msg,), daemon=True).start()
            elif "id" in msg:
                self._write({"jsonrpc": "2.0", "id": msg["id"],
                             "error": {"code": -32601, "message": "ARGON no ofrece este método"}})
        # El proceso terminó: lo que esperaba respuesta se entera.
        for done, box in list(self.pending.values()):
            box[0] = {"dead": True}
            done.set()
        self.pending.clear()

    def _on_update(self, params):
        sid = params.get("sessionId")
        if sid in self.replaying:
            return
        turn = self.turns.get(sid)
        if not turn:
            return
        u = params.get("update") or {}
        kind = u.get("sessionUpdate")
        if kind == "agent_message_chunk":
            turn.add_chunk("text", (u.get("content") or {}).get("text", ""))
        elif kind == "agent_thought_chunk":
            turn.add_chunk("thought", (u.get("content") or {}).get("text", ""))
        elif kind == "tool_call":
            with turn.lock:
                ev = turn.find(u.get("toolCallId"))
                if ev is None:
                    ev = {"t": "tool", "id": u.get("toolCallId")}
                    turn.events.append(ev)
                ev.update(title=u.get("title", ""), kind=u.get("kind", ""), status=u.get("status") or "in_progress",
                          input=content_text(u.get("content")))
            turn.flush(force=True)
        elif kind == "tool_call_update":
            with turn.lock:
                ev = turn.find(u.get("toolCallId"))
                if ev is not None:
                    if u.get("status"):
                        ev["status"] = u["status"]
                    out = content_text(u.get("content"))
                    if out and ev["t"] == "tool":
                        ev["output"] = tidy_output(out)
            turn.flush(force=True)
        elif kind == "plan":
            with turn.lock:
                turn.events = [e for e in turn.events if e["t"] != "plan"]
                turn.events.append({"t": "plan", "entries": [
                    {"text": e.get("content", ""), "status": e.get("status", "pending")}
                    for e in u.get("entries", [])]})
            turn.flush(force=True)

    def _on_permission(self, msg):
        params = msg.get("params") or {}
        turn = self.turns.get(params.get("sessionId"))
        tool = params.get("toolCall") or {}
        options = [{"id": o.get("optionId"), "kind": o.get("kind", ""),
                    "name": OPTION_NAMES.get(o.get("optionId"), o.get("name", ""))} for o in params.get("options", [])]
        choice = None
        if turn:
            choice = turn.ask({"t": "permission", "id": tool.get("toolCallId") or f"perm-{time.time()}",
                               "title": tool.get("title", "Black Hat pide permiso"),
                               "detail": content_text(tool.get("content")), "options": options,
                               "answer": None}, PERMISSION_WAIT)
        valid = {o["id"] for o in options}
        outcome = {"outcome": "selected", "optionId": choice} if choice in valid else {"outcome": "cancelled"}
        try:
            self._write({"jsonrpc": "2.0", "id": msg["id"], "result": {"outcome": outcome}})
        except (OSError, ValueError):
            pass

    # --- sesiones y turnos ---

    def session_for(self, thread):
        """Devuelve (sesión, es_nueva) del hilo. Retoma la de antes si existe."""
        mcp = [{"name": "argon", "command": "/usr/bin/python3",
                "args": [MCP_SCRIPT, "--thread", str(thread)], "env": []}]
        sid = thread_session(thread)
        if sid and sid in self.loaded:
            return sid, False
        if sid:
            for method in ("session/resume", "session/load"):
                self.replaying.add(sid)
                try:
                    self.call(method, {"sessionId": sid, "cwd": HOME, "mcpServers": mcp}, timeout=180)
                    self.loaded.add(sid)
                    return sid, False
                except RuntimeError:
                    continue
                finally:
                    self.replaying.discard(sid)
        res = self.call("session/new", {"cwd": HOME, "mcpServers": mcp}, timeout=180)
        sid = res["sessionId"]
        self.loaded.add(sid)
        set_thread_session(thread, sid)
        return sid, True

    def run(self, rid):
        item = load(rid)
        thread = item["thread"]
        lock = self.thread_locks.setdefault(thread, threading.Lock())
        with lock:  # en un mismo hilo, un turno a la vez y en orden
            if load(rid)["status"] == "cancelado":
                return
            turn = Turn(rid)
            sid = None
            try:
                self.ensure()
                sid, fresh = self.session_for(thread)
                self.turns[sid] = turn
                _active[rid] = (sid, turn)
                started = time.monotonic()
                res = self.call("session/prompt", {"sessionId": sid, "prompt": build_prompt(item, fresh)})
                stop = res.get("stopReason", "end_turn")
                if turn.looped:
                    turn.status = "falló"
                    save(rid, error=LOOP_ERROR)
                elif load(rid)["status"] == "cancelado" or stop == "cancelled":
                    turn.status = "cancelado"
                else:
                    turn.status = "respondido"
                    if stop in ("max_tokens", "max_turn_requests"):
                        with turn.lock:
                            turn.events.append({"t": "note", "text": "Black Hat llegó a su límite en este turno."})
                turn.flush(force=True)
                if time.monotonic() - started > 25 and turn.status == "respondido":
                    notify("ARGON terminó", turn.reply_text()[:160] or item["text"][:160])
            except Exception as e:  # noqa: BLE001
                turn.status = "cancelado" if load(rid)["status"] == "cancelado" and not turn.looped else "falló"
                turn.flush(force=True)
                if turn.status == "falló":
                    save(rid, error=LOOP_ERROR if turn.looped else friendly_error(str(e)))
            finally:
                if sid:
                    self.turns.pop(sid, None)
                _active.pop(rid, None)

    def cancel(self, rid):
        active = _active.get(rid)
        if not active:
            return
        sid, turn = active
        turn.release_all()
        try:
            self.send_notification("session/cancel", {"sessionId": sid})
        except (OSError, AttributeError, ValueError):
            pass


LOOP_ERROR = ("Black Hat se quedó repitiendo lo mismo y lo corté. Escribe \"sigue\" para que retome, "
              "o pídelo de otra forma.")
HERMES = Hermes()
_active = {}  # id de turno -> (sesión, Turn)


def repetition_start(text, min_reps=6, min_total=800, max_period=400):
    """Si el final de text es un mismo trozo repetido una y otra vez (un modelo en loop), devuelve dónde conviene
    cortar (dejando dos repeticiones a la vista); si no, None. Mira solo los últimos 4000 caracteres."""
    tail = text[-4000:]
    n, base = len(tail), len(text) - len(tail)
    for period in range(4, max_period + 1):
        if period * min_reps > n:
            break
        unit = tail[-period:]
        reps = 1
        while (reps + 1) * period <= n and tail[n - (reps + 1) * period:n - reps * period] == unit:
            reps += 1
        if reps >= min_reps and reps * period >= min_total:
            return base + n - (reps - 2) * period
    return None


def content_text(content):
    parts = []
    for c in content or []:
        if not isinstance(c, dict):
            continue
        inner = c.get("content")
        if isinstance(inner, dict) and inner.get("text"):
            parts.append(inner["text"])
        elif c.get("type") == "diff":
            parts.append(f'Edita {c.get("path", "")}')
    return "\n".join(parts).strip()


def tidy_output(text):
    text = re.sub(r"^terminal result\n", "", text)
    text = text.replace("- **output:** ", "").replace("- **exit_code:** ", "código de salida: ")
    lines = text.splitlines()
    if len(lines) > 16:
        text = "\n".join(lines[:16]) + f"\n… ({len(lines) - 16} líneas más)"
    return text[:3000]


def friendly_error(msg):
    low = msg.lower()
    if "strata" in low or "connection" in low or "8080" in low:
        return "Black Hat no pudo hablar con Strata. ¿Está cargado? Ábrelo con el ícono STRATA del dock."
    return msg[-600:]


def strata_sees_images():
    try:
        with urllib.request.urlopen(f"{STRATA}/v1/status", timeout=3) as r:
            return bool((json.load(r).get("vision") or {}).get("enabled"))
    except Exception:  # noqa: BLE001
        return False


def build_prompt(item, fresh):
    head = ""
    if fresh:
        head = INTRO
        earlier = earlier_turns(item["id"])
        if earlier:  # hilo de antes de ACP: le contamos lo conversado
            lines = [f'{USER_NAME}: {t["text"]}\nARGON: {(t.get("reply") or "")[:600]}' for t in earlier]
            head += "\nLo conversado antes en este hilo:\n" + "\n".join(lines) + "\n"
        head += "\n---\n"
    blocks = [{"type": "text", "text": head + item["text"]}]
    files = item.get("files") or []
    if files:
        sees = strata_sees_images()
        notes = []
        for path in files:
            mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
            name = os.path.basename(path)
            if mime.startswith("image/"):
                if sees:
                    blocks.append({"type": "resource_link", "uri": "file://" + path, "name": name, "mimeType": mime})
                    notes.append(f"- Imagen: {path}")
                else:
                    notes.append(f"- Imagen: {path} (el modelo de ahora no ve imágenes; si tienes una herramienta "
                                 "que pueda analizarla, úsala; si no, dile al usuario que la visión de Strata está apagada)")
                continue
            readable = extract_text(path, mime)
            if readable:
                blocks.append({"type": "resource_link", "uri": "file://" + readable, "name": name,
                               "mimeType": "text/plain"})
                notes.append(f"- Documento: {path}" + (f" (texto extraído en {readable})" if readable != path else ""))
            else:
                notes.append(f"- Archivo: {path} ({mime})")
        blocks[0]["text"] += f"\n\nAdjuntos de {USER_NAME}:\n" + "\n".join(notes)
    return blocks


def extract_text(path, mime):
    """Texto legible de un adjunto: tal cual si es texto; PDF y Word se convierten a un .txt al lado."""
    if mime.startswith("text/") or mime in ("application/json", "application/xml", "application/x-yaml"):
        return path
    out = path + ".txt"
    try:
        if mime == "application/pdf":
            subprocess.run(["pdftotext", "-layout", path, out], check=True, timeout=120, capture_output=True)
            return out
        if path.lower().endswith(".docx"):
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            with open(out, "w") as f:
                f.write(re.sub(r"<[^>]+>", "", xml.replace("</w:p>", "\n")))
            return out
    except (OSError, subprocess.SubprocessError, zipfile.BadZipFile, KeyError):
        return None
    return None


# --- Lo instantáneo del escritorio (sin modelo) ------------------------------

def quick_action(text):
    """Si el pedido es un atajo claro del escritorio, lo hace al tiro y devuelve qué hizo."""
    t = text.strip().lower().rstrip(".!")
    m = re.fullmatch(r"(?:ve|ir|anda|cambia|pasa|llévame)(?: al?| a)? escritorio (\d+)", t)
    if m:
        n = int(m.group(1))
        shell_call("SwitchWorkspace", GLib.Variant("(i)", (n,)))
        return f"Te llevé al escritorio {n}."
    m = re.fullmatch(r"(?:activa |pon )?(?:el )?modo foco(?: por)?(?: (\d+) ?(?:min|minutos))?", t)
    if m:
        return focus_mode(int(m.group(1) or 30))
    if re.fullmatch(r"(?:quita|quitar|apaga|desactiva) (?:el )?modo foco", t):
        return focus_mode(0)
    m = re.fullmatch(r"(?:abre|abrir|ábreme|abreme|lanza)(?: la app| la aplicación)? (?:el |la |los |las )?(.+)", t)
    if m:
        target = re.sub(r"^carpeta (?:de )?", "", m.group(1)).strip()
        for name, path in FOLDERS.items():
            if path and target == name.lower():
                Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
                return f"Abrí {name}."
        app = find_app(target, exact=True)
        if app:
            app.launch([], None)
            return f"Abrí {app.get_display_name()}."
    return None


def find_app(query, exact=False):
    q = query.lower().strip()
    best = None
    for app in Gio.AppInfo.get_all():
        if not app.should_show():
            continue
        name = (app.get_display_name() or "").lower()
        if name == q:
            return app
        if not exact and q and q in name and best is None:
            best = app
    return best


def shell_call(method, params):
    # Cambiar de escritorio virtual solo lo puede GNOME: la extensión ARGON expone esto por D-Bus.
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync("dev.argon.Shell", "/dev/argon/Shell", "dev.argon.Shell", method, params,
                  None, Gio.DBusCallFlags.NONE, 5000, None)


def focus_mode(minutes):
    global _focus_timer
    settings = Gio.Settings.new("org.gnome.desktop.notifications")
    if _focus_timer:
        _focus_timer.cancel()
        _focus_timer = None
    if minutes <= 0:
        settings.set_boolean("show-banners", True)
        return "Avisos activados."
    settings.set_boolean("show-banners", False)
    _focus_timer = threading.Timer(minutes * 60, lambda: Gio.Settings.new(
        "org.gnome.desktop.notifications").set_boolean("show-banners", True))
    _focus_timer.daemon = True
    _focus_timer.start()
    return f"Avisos silenciados por {minutes} min."


# --- Herramientas ARGON para Black Hat (llegan por argon_mcp.py) -------------

def active_turn(thread):
    for rid, (_, turn) in list(_active.items()):
        if (load(rid) or {}).get("thread") == thread:
            return turn
    return None


def tool_call(thread, name, args):
    if name == "argon_abrir_app":
        app = find_app(str(args.get("nombre", "")))
        if not app:
            raise RuntimeError(f'No encontré una app llamada "{args.get("nombre")}".')
        app.launch([], None)
        return f"Abrí {app.get_display_name()}."
    if name == "argon_abrir_carpeta":
        path = FOLDERS.get(args.get("carpeta")) or os.path.expanduser(str(args.get("carpeta", "")))
        if not os.path.isdir(path):
            raise RuntimeError(f'No existe la carpeta "{args.get("carpeta")}".')
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
        return f"Abrí {path}."
    if name == "argon_ir_a_escritorio":
        n = int(args.get("numero", 1))
        shell_call("SwitchWorkspace", GLib.Variant("(i)", (n,)))
        return f"Escritorio {n}."
    if name == "argon_modo_foco":
        return focus_mode(max(0, min(480, int(args.get("minutos", 30) or 0))))
    if name == "argon_encargo_flota":
        if not HUB_SSH:
            raise RuntimeError("No hay coordinador configurado (hub.ssh en ~/.config/argon/argon.json).")
        brief = compose_brief(args)
        turn = active_turn(thread)
        if not turn:
            raise RuntimeError("No hay una conversación activa en ARGON para confirmar el envío.")
        choice = turn.ask({"t": "confirm", "id": f"flota-{int(time.time() * 1000)}",
                           "title": f"Enviar este encargo a {HUB_NAME}", "detail": brief,
                           "options": [{"id": "send", "name": f"Enviar a {HUB_NAME}", "kind": "allow_once"},
                                       {"id": "no", "name": "No enviar", "kind": "reject_once"}],
                           "answer": None}, CONFIRM_WAIT)
        if choice != "send":
            return f"{USER_NAME} no confirmó el envío; el encargo NO se mandó."
        return send_to_hub(brief)
    raise RuntimeError(f"Herramienta desconocida: {name}")


def compose_brief(args):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def line(k, v):
        return f"{k}: {str(v or '').strip() or 'no indicado'}"
    return "\n".join([
        f"ENCARGO de {USER_NAME} desde ARGON ({SENDER}) · {now}",
        line("Objetivo", args.get("objetivo")),
        line("Alcance", args.get("alcance")),
        line("Límites", args.get("limites") or "no borrar, no gastar, no desplegar"),
        line("Evidencia esperada", args.get("evidencia")),
        f"Destino del resultado: {HUB.get('destino') or 'responde con un resumen y rutas verificables.'}",
        *([f"Protocolo: {HUB['protocolo']}"] if HUB.get("protocolo") else []),
    ])


def send_to_hub(text):
    # Comando fijo en el otro lado; el texto entra por stdin y nunca se interpreta como comando.
    remote = f'msg=$(cat); notify-hermes --to {shlex.quote(HUB_ENDPOINT)} --from {shlex.quote(SENDER)} "$msg"'
    proc = subprocess.run(["tailscale", "ssh", HUB_SSH, remote], input=text, text=True,
                          capture_output=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"No se pudo entregar a {HUB_NAME}. " + (proc.stderr.strip().splitlines() or [""])[-1])
    return f"Entregado al bus de {HUB_NAME}. Entregado no significa ejecutado."


# --- Servidor ---------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _auth(self):
        # Sin cabecera Origin: una página web no puede hablarle a argond aunque adivine el puerto.
        if self.headers.get("Origin") or self.headers.get("X-Argon-Token") != TOKEN:
            self._json(403, {"error": "sin permiso"})
            return False
        return True

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._auth():
            return
        path, _, query = self.path.partition("?")
        if path == "/status":
            with _db_lock, db() as c:
                counts = dict(c.execute("SELECT status, COUNT(*) FROM requests WHERE status IN "
                                        "('pensando','ejecutando','esperando confirmación','necesita tu permiso') "
                                        "GROUP BY status").fetchall())
            return self._json(200, {"thinking": counts.get("pensando", 0), "running": counts.get("ejecutando", 0),
                                    "waiting": counts.get("esperando confirmación", 0)
                                    + counts.get("necesita tu permiso", 0), "hermes": HERMES.alive})
        if path == "/requests":
            m = re.search(r"limit=(\d+)", query)
            limit = min(int(m.group(1)) if m else 50, 500)
            with _db_lock, db() as c:
                rows = c.execute("SELECT * FROM requests ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return self._json(200, [row_dict(r) for r in rows])
        m = re.fullmatch(r"/requests/(\d+)", path)
        if m:
            item = load(int(m.group(1)))
            return self._json(200 if item else 404, item or {"error": "no existe"})
        self._json(404, {"error": "ruta desconocida"})

    def do_POST(self):
        if not self._auth():
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(400, {"error": "JSON inválido"})
        if self.path == "/requests":
            return self._new_request(payload)
        if self.path == "/tools/call":
            try:
                text = tool_call(int(payload.get("thread") or 0), str(payload.get("name", "")),
                                 payload.get("args") or {})
                return self._json(200, {"text": text})
            except Exception as e:  # noqa: BLE001
                return self._json(200, {"text": str(e), "error": True})
        m = re.fullmatch(r"/requests/(\d+)/(answer|cancel|confirm)", self.path)
        if not m:
            return self._json(404, {"error": "ruta desconocida"})
        rid, action = int(m.group(1)), m.group(2)
        item = load(rid)
        if not item:
            return self._json(404, {"error": "no existe"})
        if action == "answer":
            active = _active.get(rid)
            ok = bool(active) and active[1].answer(str(payload.get("event")), str(payload.get("option")))
            return self._json(200 if ok else 409, {"ok": ok})
        if action == "confirm":  # los planes del ARGON anterior ya no se ejecutan
            return self._json(409, {"error": "este pedido es de la versión anterior de ARGON"})
        if item["status"] in ("pensando", "necesita tu permiso", "esperando confirmación", "ejecutando"):
            save(rid, status="cancelado")
            HERMES.cancel(rid)
        return self._json(200, {"ok": True})

    def _new_request(self, payload):
        text = str(payload.get("text", "")).strip()
        files = [os.path.abspath(f) for f in payload.get("files") or [] if isinstance(f, str) and os.path.isfile(f)]
        if not text and not files:
            return self._json(400, {"error": "el pedido está vacío"})
        text = text or "Revisa lo que te adjunto."
        now = time.time()
        thread = payload.get("thread")
        with _db_lock, db() as c:
            if thread is not None and not c.execute("SELECT 1 FROM requests WHERE thread=?",
                                                    (int(thread),)).fetchone():
                thread = None
            rid = c.execute("INSERT INTO requests (created, updated, text, steps, status, thread, files, events, kind) "
                            "VALUES (?,?,?,?,?,?,?,?,?)",
                            (now, now, text, "[]", "pensando", int(thread) if thread is not None else None,
                             json.dumps(files), "[]", "agente")).lastrowid
            if thread is None:
                c.execute("UPDATE requests SET thread=? WHERE id=?", (rid, rid))
        result = None
        if not files:
            try:
                result = quick_action(text)
            except Exception as e:  # noqa: BLE001
                result = f"No pude: {e}"
        if result:
            save(rid, kind="local", status="hecho", reply=result, events=[{"t": "local", "text": result}])
        else:
            threading.Thread(target=HERMES.run, args=(rid,), daemon=True).start()
        return self._json(200, {"id": rid})


def main():
    global TOKEN
    init_db()
    with open(TOKEN_PATH) as f:
        TOKEN = f.read().strip()
    # Hermes arranca de inmediato para que el primer mensaje no espere el arranque.
    threading.Thread(target=HERMES.ensure, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
