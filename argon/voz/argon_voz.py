#!/usr/bin/env python3
"""ARGON — servicio de voz.

Escucha el micrófono, transcribe con Whisper (en el procesador, para no tocar la tarjeta gráfica que usa
Strata) y lee las respuestas en voz alta con Piper. Todo corre en este equipo.

API local en 127.0.0.1:8738, con la misma clave que argond (cabecera X-Argon-Token):
  POST /listen        graba hasta que dejas de hablar (o hasta /listen/stop) y devuelve {"text"}
  POST /listen/stop   corta la grabación en curso
  POST /speak         {"text"} lo lee en voz alta (corta lo que estuviera diciendo)
  POST /speak/stop    se calla
  GET  /status        {"listening", "speaking"}

Corre con el Python de ~/.local/share/argon/voz (ahí están faster-whisper y piper).
"""
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from faster_whisper import WhisperModel
from piper import PiperVoice

HOME = os.path.join(os.path.expanduser("~"), ".local", "share", "argon")
TOKEN_PATH = os.path.join(HOME, "token")
WHISPER_DIR = os.path.join(HOME, "modelos", "whisper-small")
PIPER_MODEL = os.path.join(HOME, "modelos", "piper", "es_MX-claude-high.onnx")
PORT = 8738

RATE = 16000
CHUNK = RATE // 10 * 2          # 100 ms de audio s16 mono
SILENCE_END = 1.4               # segundos de silencio, después de hablar, que cierran la frase
NO_SPEECH_GIVEUP = 8.0          # si no dices nada en este tiempo, deja de escuchar
MAX_SECONDS = 60.0
# Palabras que Whisper suele confundir: se las damos como contexto.
VOCAB = "ARGON, Black Hat, Strata, Hermes, Tailscale, gigas, escritorio."


def read_token():
    with open(TOKEN_PATH) as f:
        return f.read().strip()


class Ear:
    """Graba con pw-record y corta solo cuando terminas de hablar."""

    def __init__(self):
        self.model = WhisperModel(WHISPER_DIR, device="cpu", compute_type="int8", cpu_threads=8)
        self.lock = threading.Lock()
        self.proc = None
        self.stop_flag = threading.Event()

    @property
    def listening(self):
        return self.proc is not None

    def listen(self):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("ya estoy escuchando")
        try:
            self.stop_flag.clear()
            self.proc = subprocess.Popen(
                ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            audio = self._capture()
        finally:
            if self.proc:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            self.proc = None
            self.lock.release()
        if audio.size < RATE // 3:
            return ""
        segs, _ = self.model.transcribe(audio, language="es", beam_size=3, vad_filter=True,
                                        initial_prompt=VOCAB)
        text = "".join(s.text for s in segs).strip()
        # Whisper a veces devuelve el propio contexto cuando no hubo voz.
        return "" if text.strip(" .") == VOCAB.strip(" .") else text

    def _capture(self):
        chunks, start = [], time.monotonic()
        noise = None
        spoke_at = last_voice = None
        while not self.stop_flag.is_set():
            data = self.proc.stdout.read(CHUNK)
            if not data:
                break
            pcm = np.frombuffer(data, np.int16).astype(np.float32) / 32768
            chunks.append(pcm)
            level = float(np.sqrt(np.mean(pcm * pcm))) if pcm.size else 0.0
            now = time.monotonic() - start
            if now < 0.3:  # el primer instante mide el ruido de la pieza
                noise = level if noise is None else max(noise, level)
                continue
            threshold = max(0.012, (noise or 0) * 2.5)
            if level > threshold:
                last_voice = now
                spoke_at = spoke_at or now
            if spoke_at is None and now > NO_SPEECH_GIVEUP:
                break
            if spoke_at is not None and now - last_voice > SILENCE_END:
                break
            if now > MAX_SECONDS:
                break
        return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)

    def stop(self):
        self.stop_flag.set()


class Mouth:
    """Lee en voz alta frase por frase, para que empiece a hablar enseguida."""

    def __init__(self):
        self.voice = PiperVoice.load(PIPER_MODEL)
        self.generation = 0
        self.player = None
        self.lock = threading.Lock()

    @property
    def speaking(self):
        return self.player is not None

    def say(self, text):
        self.stop()
        with self.lock:
            self.generation += 1
            gen = self.generation
        threading.Thread(target=self._run, args=(gen, clean_for_speech(text)), daemon=True).start()

    def _run(self, gen, text):
        for chunk in self.voice.synthesize(text):
            if gen != self.generation:
                return
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                path = tmp.name
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(chunk.sample_rate)
                w.writeframes(chunk.audio_int16_bytes)
            try:
                if gen != self.generation:
                    return
                self.player = subprocess.Popen(["pw-play", path], stderr=subprocess.DEVNULL)
                self.player.wait()
            finally:
                self.player = None
                os.unlink(path)

    def stop(self):
        with self.lock:
            self.generation += 1
        player = self.player
        if player:
            player.terminate()


def clean_for_speech(text):
    """Saca lo que suena mal leído: código, rutas largas, viñetas y enlaces."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"https?://\S+", "el enlace", text)
    text = re.sub(r"[*_#>|]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1200]


EAR = MOUTH = None
TOKEN = ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if self.headers.get("Origin") or self.headers.get("X-Argon-Token") != TOKEN:
            self.reply(403, {"error": "sin permiso"})
            return False
        return True

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == "/status":
            return self.reply(200, {"listening": EAR.listening, "speaking": MOUTH.speaking})
        self.reply(404, {"error": "no existe"})

    def do_POST(self):
        if not self.authorized():
            return
        try:
            if self.path == "/listen":
                MOUTH.stop()  # si estaba hablando, se calla para escucharte
                return self.reply(200, {"text": EAR.listen()})
            if self.path == "/listen/stop":
                EAR.stop()
                return self.reply(200, {"ok": True})
            if self.path == "/speak":
                text = str(self.body().get("text", "")).strip()
                if text:
                    MOUTH.say(text)
                return self.reply(200, {"ok": True})
            if self.path == "/speak/stop":
                MOUTH.stop()
                return self.reply(200, {"ok": True})
        except RuntimeError as e:
            return self.reply(409, {"error": str(e)})
        except Exception as e:  # noqa: BLE001 — el servicio no debe caerse por un pedido
            return self.reply(500, {"error": str(e)})
        self.reply(404, {"error": "no existe"})


def main():
    global EAR, MOUTH, TOKEN
    TOKEN = read_token()
    EAR, MOUTH = Ear(), Mouth()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    print(f"argon-voz escuchando en 127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
