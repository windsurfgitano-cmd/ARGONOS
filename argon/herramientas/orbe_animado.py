"""Convierte el video del orbe de plasma en cuadros PNG con transparencia, en bucle.

El plasma es luz sobre negro, así que la transparencia sale del brillo: un píxel negro queda
transparente y uno brillante queda opaco. Un fundido entre el final y el inicio del tramo hace
que el bucle no tenga corte aunque el tramo sea corto.

Uso (desde argon/):
  python3 herramientas/orbe_animado.py VIDEO SALIDA --start 2 --seconds 4 --fps 20 --size 440
"""
import argparse
import os
import subprocess
import tempfile

import numpy as np
from PIL import Image


def extract(video, start, seconds, fps, size, tmp):
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(seconds), "-i", video,
        "-vf", f"fps={fps},scale={size}:{size}:flags=lanczos", os.path.join(tmp, "f%04d.png"),
    ], check=True)
    names = sorted(n for n in os.listdir(tmp) if n.endswith(".png"))
    return [np.asarray(Image.open(os.path.join(tmp, n)).convert("RGB"), np.float32) / 255 for n in names]


def to_rgba(rgb, mask):
    # Negro puro del video -> transparente. Se resta un poco de "piso" para borrar el ruido del fondo.
    alpha = np.clip((rgb.max(axis=2) - 0.03) / 0.97, 0, 1) * mask
    safe = np.maximum(alpha, 1e-4)[..., None]
    color = np.clip(rgb / safe, 0, 1)  # se des-premultiplica: compuesto sobre negro se ve igual que el video
    out = np.dstack([color, alpha])
    return Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGBA")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--start", type=float, default=2.0)
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--size", type=int, default=440)
    ap.add_argument("--fade", type=float, default=0.8, help="segundos de fundido para cerrar el bucle")
    ap.add_argument("--radius", type=float, default=0.76, help="radio del recorte (1 = borde del cuadro)")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        frames = extract(args.video, args.start, args.seconds + args.fade, args.fps, args.size, tmp)

    n_fade = max(1, int(args.fade * args.fps))
    loop = frames[:-n_fade] if len(frames) > n_fade * 2 else frames
    # Fundido: los últimos cuadros del tramo se mezclan con los que vienen justo después,
    # que son los mismos que el comienzo desplazado; así el final calza con el inicio.
    tail = frames[len(loop):]
    for i, extra in enumerate(tail):
        t = (i + 1) / (len(tail) + 1)
        loop[i] = loop[i] * t + extra * (1 - t)

    yy, xx = np.mgrid[0:args.size, 0:args.size].astype(np.float32)
    r = np.hypot(xx - args.size / 2, yy - args.size / 2) / (args.size / 2)
    mask = np.clip((args.radius - r) / 0.06, 0, 1)  # recorte circular suave: deja la esfera y un halo corto

    os.makedirs(args.out, exist_ok=True)
    for old in os.listdir(args.out):
        if old.startswith("orb-") and old.endswith(".png"):
            os.remove(os.path.join(args.out, old))
    for i, rgb in enumerate(loop):
        to_rgba(rgb, mask).save(os.path.join(args.out, f"orb-{i:03d}.png"), optimize=True)
    total = sum(os.path.getsize(os.path.join(args.out, f)) for f in os.listdir(args.out) if f.startswith("orb-"))
    print(f"{len(loop)} cuadros · {args.fps} cuadros/s · {total / 1e6:.1f} MB en {args.out}")


if __name__ == "__main__":
    main()
