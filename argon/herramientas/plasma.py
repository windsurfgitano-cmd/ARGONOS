"""Renderiza el fondo animado de ARGON: una cinta de plasma de argón sobre verde phthalo.

El bucle es exacto: todo movimiento depende de un ángulo que da una vuelta completa
en la duración del video, y cada onda usa un número entero de vueltas.

Uso (desde la carpeta argon/):
  python3 herramientas/plasma.py --preview fondos/plasma-preview.png      # un cuadro
  python3 herramientas/plasma.py --video fondos/argon-plasma.mp4          # el bucle completo
Opciones: --width 2560 --height 1440 --fps 30 --seconds 20
"""
import argparse
import math
import os
import subprocess
import sys
from multiprocessing import Pool

import numpy as np

# Paleta (lineal 0..1).
BG_TOP = np.array([0.022, 0.095, 0.062], np.float32)     # verde phthalo, arriba a la izquierda
BG_BOTTOM = np.array([0.008, 0.036, 0.024], np.float32)
CORE = np.array([1.00, 0.95, 1.00], np.float32)          # centro de los hilos principales
VIOLET = np.array([0.58, 0.36, 1.00], np.float32)        # violeta argón
BLUE = np.array([0.22, 0.26, 1.00], np.float32)          # resplandor azulado
SMOKE = np.array([0.07, 0.36, 0.24], np.float32)         # humo verde phthalo

SEED = 18  # número atómico del argón
BUNDLES = 3        # hilos principales que se trenzan
HAIRS = 34         # pelitos finos que siguen a cada hilo principal


def wave(x, theta, waves):
    y = 0.0
    for freq, amp, phase, turns in waves:
        y = y + amp * np.sin(freq * x * 2 * math.pi + phase + turns * theta)
    return y


def random_waves(rng, n, fmin, fmax, amin, amax, max_turns):
    out = []
    for _ in range(n):
        turns = int(rng.integers(1, max_turns + 1)) * (1 if rng.random() < 0.5 else -1)
        out.append((rng.uniform(fmin, fmax), rng.uniform(amin, amax), rng.uniform(0, 2 * math.pi), turns))
    return out


class Scene:
    def __init__(self, width, height, frames, smoke=0.0, logo=None):
        self.w, self.h, self.frames = width, height, frames
        self.smoke_amount = smoke
        rng = np.random.default_rng(SEED)
        self.x = np.linspace(0.0, 1.0, width, dtype=np.float32)
        ys = np.linspace(0.0, 1.0, height, dtype=np.float32)

        # La cinta entra por la derecha y se adelgaza hacia la izquierda, como en el fondo original.
        self.envelope = np.clip((self.x - 0.14) / 0.86, 0, 1) ** 1.05
        self.center = 0.47 + 0.015 * np.sin(self.x * 4.0)

        self.bundles = []
        for _ in range(BUNDLES):
            main = random_waves(rng, 2, 0.6, 1.5, 0.05, 0.11, 1)
            hairs = []
            for _ in range(HAIRS):
                jitter = random_waves(rng, 2, 3.0, 9.0, 0.004, 0.02, 2)
                offset = rng.normal(0.0, 0.034)
                bright = rng.uniform(0.15, 1.0) ** 2.2
                hairs.append((jitter, offset, bright, rng.uniform(0.6, 1.6)))
            self.bundles.append((main, hairs))

        # Solo se dibuja la franja donde vive la cinta (ahorra tiempo).
        self.y0 = int(height * 0.12)
        self.y1 = int(height * 0.86)
        self.Y = ys[self.y0:self.y1, None]

        # Fondo estático: degradado diagonal, viñeta y grano fino.
        gx, gy = np.meshgrid(self.x, ys)
        t = np.clip(0.55 * gx + 0.45 * gy, 0, 1)[..., None]
        bg = BG_TOP * (1 - t) + BG_BOTTOM * t
        vignette = 1 - 0.6 * (((gx - 0.5) ** 2) * 1.2 + ((gy - 0.5) ** 2) * 1.6)
        bg *= np.clip(vignette, 0.3, 1)[..., None]
        bg += rng.normal(0, 0.004, (height, width, 1)).astype(np.float32)
        self.background = bg.astype(np.float32)

        # Humo: se calcula en una malla chica (1/8) y se amplía; es suave, no necesita más detalle.
        sw, sh = max(8, width // 4), max(8, height // 4)
        self.sx, self.sy = np.meshgrid(np.linspace(0, 1, sw, dtype=np.float32), np.linspace(0, 1, sh, dtype=np.float32))
        self.smoke_waves = [(rng.uniform(1.0, 4.0), rng.uniform(1.0, 4.0), rng.uniform(0, 2 * math.pi),
                             int(rng.integers(1, 3)) * (1 if rng.random() < 0.5 else -1), 0.55 ** k) for k in range(4)]
        # El humo vive sobre todo a la izquierda y abajo, dejando aire alrededor de la cinta.
        self.smoke_mask = np.clip(1.1 - self.sx * 0.7 - np.abs(self.sy - 0.62) * 0.9, 0, 1) ** 1.5

        # Logo opcional al centro (PNG con transparencia), mezclado de forma sutil.
        self.logo = None
        if logo:
            from PIL import Image
            im = Image.open(logo).convert("RGBA")
            scale = height / 1440
            im = im.resize((int(im.width * scale * 0.5), int(im.height * scale * 0.5)), Image.LANCZOS)
            a = np.asarray(im, np.float32) / 255
            self.logo = (a, (width - im.width) // 2, int(height * 0.27))

    def smoke(self, theta):
        from PIL import Image
        x, y = self.sx, self.sy
        # Deformación del dominio: hace que las ondas se vean como humo y no como rayas.
        wx = x + 0.12 * np.sin(2 * math.pi * (1.3 * y) + theta)
        wy = y + 0.10 * np.sin(2 * math.pi * (1.1 * x) - theta)
        f = np.zeros_like(x)
        for fx, fy, ph, turns, amp in self.smoke_waves:
            f += amp * np.sin(2 * math.pi * (fx * wx + fy * wy) + ph + turns * theta)
            wx, wy = wy * 1.5 + 0.3, wx * 1.5 - 0.2
        from PIL import ImageFilter
        f = np.clip((f / 2.0 + 0.5), 0, 1) ** 1.8 * self.smoke_mask
        small = Image.fromarray((f * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))
        big = small.resize((self.w, self.h), Image.BICUBIC)
        return np.asarray(big, np.float32)[..., None] / 255

    def frame(self, n):
        theta = 2 * math.pi * n / self.frames
        px = 1.0 / self.h
        env = self.envelope
        hair_light = np.zeros((self.y1 - self.y0, self.w), np.float32)
        core_light = np.zeros_like(hair_light)
        glow = np.zeros_like(hair_light)

        for b, (main, hairs) in enumerate(self.bundles):
            y_main = self.center + env * wave(self.x, theta, main)
            d_main = (self.Y - y_main[None, :]) / px
            # Hilo principal: núcleo blanco fino y resplandor ancho.
            core_w = 1.3 + 1.6 * env
            pulse = 0.8 + 0.2 * math.sin(theta + b * 2.1)
            core_light += pulse * np.exp(-(d_main * d_main) / (2 * core_w * core_w)) * env
            glow += pulse * np.exp(-np.abs(d_main) / (10 + 70 * env)) * env
            for jitter, offset, bright, wpx in hairs:
                y = y_main + env * (offset * (0.4 + env) + wave(self.x, theta, jitter))
                d = (self.Y - y[None, :]) / px
                w = wpx * (0.5 + 0.8 * env)
                hair_light += bright * np.exp(-(d * d) / (2 * w * w)) * env

        img = self.background.copy()
        if self.smoke_amount > 0:
            img += self.smoke(theta) * SMOKE * self.smoke_amount
        band = img[self.y0:self.y1]
        band += (glow * 0.22)[..., None] * (BLUE * 0.65 + VIOLET * 0.35)
        band += (hair_light * 0.40)[..., None] * (VIOLET * 0.7 + BLUE * 0.3)
        band += (core_light * 0.9)[..., None] * VIOLET
        band += np.clip(core_light - 0.45, 0, 1)[..., None] * (CORE - VIOLET) * 1.2
        # Tono suave solo para que los brillos no se quemen; las sombras quedan profundas.
        img = img / (1 + 0.6 * img)
        img = np.clip(img * 1.25, 0, 1)
        if self.logo is not None:
            a, lx, ly = self.logo
            h, w = a.shape[:2]
            alpha = a[..., 3:4] * 0.55
            region = img[ly:ly + h, lx:lx + w]
            region[:] = region * (1 - alpha) + a[..., :3] * alpha
        return (img * 255 + 0.5).astype(np.uint8)


_scene = None


def _init(width, height, frames, smoke, logo):
    global _scene
    _scene = Scene(width, height, frames, smoke, logo)


def _render(n):
    return _scene.frame(n).tobytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=2560)
    ap.add_argument("--height", type=int, default=1440)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--preview")
    ap.add_argument("--video")
    ap.add_argument("--smoke", type=float, default=0.0, help="intensidad del humo verde (0 = sin humo)")
    ap.add_argument("--logo", help="PNG con transparencia para poner al centro")
    args = ap.parse_args()
    frames = args.fps * args.seconds

    if args.preview:
        from PIL import Image
        Image.fromarray(Scene(args.width, args.height, frames, args.smoke, args.logo).frame(0)).save(args.preview)
        print("vista previa:", args.preview)
        return

    if not args.video:
        ap.error("usa --preview o --video")

    ffmpeg = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{args.width}x{args.height}", "-r", str(args.fps), "-i", "-",
        "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", args.video,
    ], stdin=subprocess.PIPE)
    workers = max(1, (os.cpu_count() or 4) - 2)
    with Pool(workers, initializer=_init, initargs=(args.width, args.height, frames, args.smoke, args.logo)) as pool:
        for i, data in enumerate(pool.imap(_render, range(frames), chunksize=2), 1):
            ffmpeg.stdin.write(data)
            if i % 30 == 0 or i == frames:
                print(f"\r{i}/{frames} cuadros", end="", file=sys.stderr, flush=True)
    ffmpeg.stdin.close()
    ffmpeg.wait()
    print("\nvideo:", args.video)


if __name__ == "__main__":
    main()
