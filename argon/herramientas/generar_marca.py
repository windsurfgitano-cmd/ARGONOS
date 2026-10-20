"""Genera el kit de marca de ARGON y las imágenes del tema de arranque.

Entrada:  marca/orbe-original.png (orbe de Higgsfield, 2048x2048 con transparencia)
Salidas:  marca/orbe-1024.png, marca/orbe-256.png, marca/icono-argon.png, marca/avatar-argon.png,
          marca/wordmark.png, plymouth-argon/{orb.png, wordmark.png, bar-bg.png, bar-fg.png}

Uso: python3 herramientas/generar_marca.py   (desde la carpeta argon/)
"""
import math
import os

import cairo
import io

from PIL import Image, ImageDraw, ImageFont

ARGON = (0.643, 0.545, 1.0)        # violeta del argón (#a48bff)
ARGON_DEEP = (0.427, 0.310, 0.878)  # #6d4fe0
PHTHALO_BG = (0.027, 0.067, 0.051)  # #07110d
FG = (0.90, 0.90, 0.94)
FONT = "Ubuntu Sans"
FONT_FILE = "/usr/share/fonts/truetype/ubuntu/UbuntuSans[wdth,wght].ttf"

# Esfera dentro del orbe original (medida sobre la imagen de 2048 px).
SPHERE_CX, SPHERE_CY, SPHERE_R = 988, 978, 718


def clean_orb(size):
    """Recorta la esfera (sin el halo con bandas) y le pone un brillo radial suave."""
    src = cairo.ImageSurface.create_from_png("marca/orbe-original.png")
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(out)
    c = size / 2
    r = size * 0.34  # radio de la esfera; el resto es brillo

    glow = cairo.RadialGradient(c, c, r * 0.9, c, c, size / 2)
    glow.add_color_stop_rgba(0, *ARGON, 0.55)
    glow.add_color_stop_rgba(0.35, *ARGON_DEEP, 0.22)
    glow.add_color_stop_rgba(1, *ARGON_DEEP, 0)
    cr.set_source(glow)
    cr.paint()

    cr.save()
    cr.arc(c, c, r, 0, 2 * math.pi)
    cr.clip()
    k = r / SPHERE_R
    cr.translate(c - SPHERE_CX * k, c - SPHERE_CY * k)
    cr.scale(k, k)
    cr.set_source_surface(src, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_BEST)
    cr.paint()
    cr.restore()
    return out


def icon(size, bg):
    """Ícono cuadrado redondeado con el orbe, para el kit de marca y el avatar."""
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(out)
    if bg == "rounded":
        rad = size * 0.22
        cr.new_sub_path()
        for x, y, a in ((size - rad, rad, -90), (size - rad, size - rad, 0), (rad, size - rad, 90), (rad, rad, 180)):
            cr.arc(x, y, rad, math.radians(a), math.radians(a + 90))
        cr.close_path()
    else:
        cr.arc(size / 2, size / 2, size / 2, 0, 2 * math.pi)
    grad = cairo.LinearGradient(0, 0, 0, size)
    grad.add_color_stop_rgb(0, 0.059, 0.165, 0.118)
    grad.add_color_stop_rgb(1, *PHTHALO_BG)
    cr.set_source(grad)
    cr.fill_preserve()
    cr.clip()
    orb = clean_orb(int(size * 1.15))
    off = (size - orb.get_width()) / 2
    cr.set_source_surface(orb, off, off)
    cr.paint()
    return out


def wordmark(scale):
    """'Ar 18' + A R G O N en letras finas espaciadas."""
    w, h = int(560 * scale), int(150 * scale)
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(out)

    # Casilla de la tabla periódica.
    bw, bh = 40 * scale, 46 * scale
    bx, by = (w - bw) / 2, 0.5 * scale
    cr.set_line_width(1.2 * scale)
    cr.set_source_rgba(*FG, 0.45)
    cr.rectangle(bx, by, bw, bh)
    cr.stroke()
    cr.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    opts = cairo.FontOptions()
    opts.set_antialias(cairo.ANTIALIAS_GRAY)  # el suavizado por subpíxel deja bordes de color sobre transparencia
    cr.set_font_options(opts)
    cr.set_source_rgba(*FG, 0.9)
    cr.set_font_size(17 * scale)
    ext = cr.text_extents("Ar")
    cr.move_to(bx + (bw - ext.x_advance) / 2, by + 24 * scale)
    cr.show_text("Ar")
    cr.set_font_size(9 * scale)
    cr.set_source_rgba(*FG, 0.55)
    ext = cr.text_extents("18")
    cr.move_to(bx + (bw - ext.x_advance) / 2, by + 39 * scale)
    cr.show_text("18")

    # Nombre con espaciado amplio. La fuente es variable: Pillow fija el peso Light (300),
    # cosa que la API básica de cairo no permite.
    font = ImageFont.truetype(FONT_FILE, int(40 * scale))
    font.set_variation_by_axes([100, 300])
    tracking = int(30 * scale)
    widths = [font.getlength(ch) for ch in "ARGON"]
    total = int(sum(widths) + tracking * 4)
    img = Image.new("RGBA", (total + 4, int(60 * scale)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x = 0
    rgba = tuple(int(v * 255) for v in FG) + (242,)
    for ch, cw in zip("ARGON", widths):
        draw.text((x, 0), ch, font=font, fill=rgba)
        x += cw + tracking
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    text = cairo.ImageSurface.create_from_png(buf)
    cr.set_source_surface(text, (w - total) / 2, 80 * scale)
    cr.paint()
    return out


def login_logo(scale):
    """'A R G O N  O S' en una línea, para el pie de la pantalla de inicio de sesión (reemplaza el logo de Ubuntu)."""
    font = ImageFont.truetype(FONT_FILE, int(36 * scale))
    font.set_variation_by_axes([100, 300])
    tracking = int(16 * scale)
    word, gap = "ARGON", int(34 * scale)
    widths = [font.getlength(ch) for ch in word]
    os_w = [font.getlength(ch) for ch in "OS"]
    total = int(sum(widths) + tracking * 4 + gap + sum(os_w) + tracking)
    img = Image.new("RGBA", (total + 8, int(52 * scale)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x = 4
    for ch, cw in zip(word, widths):
        draw.text((x, 2 * scale), ch, font=font, fill=tuple(int(v * 255) for v in FG) + (242,))
        x += cw + tracking
    x += gap - tracking
    for ch, cw in zip("OS", os_w):  # "OS" en violeta argón
        draw.text((x, 2 * scale), ch, font=font, fill=tuple(int(v * 255) for v in ARGON) + (242,))
        x += cw + tracking
    return img


def bar(width, height, color, alpha):
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(out)
    cr.set_source_rgba(*color, alpha)
    cr.rectangle(0, 0, width, height)
    cr.fill()
    return out


def main():
    os.makedirs("marca", exist_ok=True)
    os.makedirs("plymouth-argon", exist_ok=True)
    os.makedirs("login-argon", exist_ok=True)
    clean_orb(1024).write_to_png("marca/orbe-1024.png")
    clean_orb(256).write_to_png("marca/orbe-256.png")
    icon(512, "rounded").write_to_png("marca/icono-argon.png")
    icon(512, "circle").write_to_png("marca/avatar-argon.png")
    wordmark(2).write_to_png("marca/wordmark.png")

    # Pantalla de arranque. Plymouth escala por pantalla HiDPI, así que va a 2x.
    clean_orb(440).write_to_png("plymouth-argon/orb.png")
    wordmark(2).write_to_png("plymouth-argon/wordmark.png")
    login_logo(2).save("login-argon/argon-os-logo.png")
    bar(480, 4, FG, 0.14).write_to_png("plymouth-argon/bar-bg.png")
    bar(480, 4, ARGON, 1.0).write_to_png("plymouth-argon/bar-fg.png")
    print("listo")


if __name__ == "__main__":
    main()
