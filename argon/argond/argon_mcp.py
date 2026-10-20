#!/usr/bin/env python3
"""Herramientas de ARGON para Black Hat, como servidor MCP (stdio).

Hermes lo arranca por cada hilo de ARGON (argond se lo pasa al abrir la sesión, con --thread N). Cada
herramienta se la pide a argond, que es quien toca el escritorio y quien le pregunta al usuario antes de mandar
un encargo al coordinador de la flota.
"""
import json
import os
import sys
import urllib.request

API = "http://127.0.0.1:8737/tools/call"
TOKEN_PATH = os.path.join(os.path.expanduser("~"), ".local", "share", "argon", "token")
CONFIG_PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "argon", "argon.json")
try:
    with open(CONFIG_PATH) as _f:
        CONFIG = json.load(_f)
except (OSError, ValueError):
    CONFIG = {}
HUB_NAME = (CONFIG.get("hub") or {}).get("nombre", "el coordinador")
FOLDERS = ["Inicio", "Documentos", "Descargas", "Imágenes", "Música", "Vídeos", "Escritorio",
           *(CONFIG.get("carpetas") or {})]

TOOLS = [
    {"name": "argon_abrir_app", "description": "Abre una aplicación del escritorio por su nombre.",
     "inputSchema": {"type": "object", "properties": {"nombre": {"type": "string", "description": "Ej: Firefox"}},
                     "required": ["nombre"]}},
    {"name": "argon_abrir_carpeta",
     "description": "Abre una carpeta en el gestor de archivos (una conocida o una ruta).",
     "inputSchema": {"type": "object", "properties": {"carpeta": {
         "type": "string", "description": "Una de " + ", ".join(FOLDERS) + ", o una ruta absoluta"}},
         "required": ["carpeta"]}},
    {"name": "argon_ir_a_escritorio", "description": "Cambia al escritorio virtual indicado (desde 1).",
     "inputSchema": {"type": "object", "properties": {"numero": {"type": "integer", "minimum": 1}},
                     "required": ["numero"]}},
    {"name": "argon_modo_foco", "description": "Silencia los avisos del escritorio esos minutos; 0 los reactiva.",
     "inputSchema": {"type": "object", "properties": {"minutos": {"type": "integer", "minimum": 0}},
                     "required": ["minutos"]}},
    {"name": "argon_encargo_flota",
     "description": (f"Manda un encargo a {HUB_NAME}, el coordinador de la flota. Úsala para todo lo de la "
                     "flota. ARGON le muestra el encargo al usuario y SOLO se envía si confirma."),
     "inputSchema": {"type": "object", "properties": {
         "objetivo": {"type": "string"}, "alcance": {"type": "string"},
         "limites": {"type": "string", "description": "Lo que NO debe hacer (por defecto: no borrar, no gastar, "
                                                      "no desplegar)"},
         "evidencia": {"type": "string", "description": "Qué debe entregar como prueba"}},
         "required": ["objetivo"]}},
]
if not (CONFIG.get("hub") or {}).get("ssh"):
    TOOLS = [t for t in TOOLS if t["name"] != "argon_encargo_flota"]


def call_argond(thread, name, args):
    with open(TOKEN_PATH) as f:
        token = f.read().strip()
    req = urllib.request.Request(API, data=json.dumps({"thread": thread, "name": name, "args": args}).encode(),
                                 headers={"X-Argon-Token": token, "Content-Type": "application/json"})
    # Un encargo espera la confirmación del usuario (hasta 15 min).
    with urllib.request.urlopen(req, timeout=20 * 60) as r:
        return json.load(r)


def main():
    thread = int(sys.argv[sys.argv.index("--thread") + 1]) if "--thread" in sys.argv else 0
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" not in msg:
            continue  # notificaciones (initialized, cancelled)
        method, params = msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "argon", "version": "1.0"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            try:
                res = call_argond(thread, params.get("name"), params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": res.get("text", "")}],
                          "isError": bool(res.get("error"))}
            except Exception as e:  # noqa: BLE001
                result = {"content": [{"type": "text", "text": f"ARGON no respondió: {e}"}], "isError": True}
        elif method == "ping":
            result = {}
        else:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                                         "error": {"code": -32601, "message": "método desconocido"}}) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
