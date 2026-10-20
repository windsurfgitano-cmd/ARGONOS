"""Arma el tema de la pantalla de inicio de sesión (GDM) de ARGON.

En GNOME 50 esa pantalla carga `gdm.css`, no los estilos del escritorio. Marble deja `gdm.css`
con el estilo de GNOME, así que aquí se reemplaza por los estilos de Marble-argon más una capa ARGON
y el fondo de humo desenfocado.

Entrada:  el gresource que generó Marble (/usr/share/gnome-shell/gnome-shell-theme.gresource)
          y argon/fondos/argon-humo-fijo.png
Salida:   argon/login-argon/gnome-shell-theme.gresource  (lo instala instalar/aplicar-tema-login.sh)

Uso (desde argon/): python3 herramientas/armar_tema_login.py
"""
import os
import shutil
import subprocess
import tempfile

from PIL import Image, ImageEnhance, ImageFilter

SOURCE = "/usr/share/gnome-shell/gnome-shell-theme.gresource"
PREFIX = "/org/gnome/shell/theme/"
OUT_DIR = "login-argon"
BACKGROUND = "fondos/argon-fondo-wan-fijo.png"

ARGON_CSS = """
/* ===== ARGON: pantalla de inicio de sesión ===== */
#lockDialogGroup {
  background-color: #07160f;
  background-image: url("resource:///org/gnome/shell/theme/argon-login.jpg");
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
}

.login-dialog,
.unlock-dialog {
  background-color: transparent;
  color: #e6f2ec;
}

/* Lista de usuarios: tarjetas de vidrio verde, la elegida en violeta. */
.login-dialog-user-list-view .login-dialog-user-list .login-dialog-user-list-item {
  background-color: rgba(4, 30, 27, 0.72);
  border: 1px solid rgba(207, 233, 221, 0.14);
  border-radius: 18px;
  color: #e6f2ec;
}
.login-dialog-user-list-view .login-dialog-user-list .login-dialog-user-list-item:hover,
.login-dialog-user-list-view .login-dialog-user-list .login-dialog-user-list-item:focus,
.login-dialog-user-list-view .login-dialog-user-list .login-dialog-user-list-item:selected {
  background-color: rgba(62, 47, 150, 0.85);
  border-color: rgba(164, 139, 255, 0.7);
}

/* Campo de contraseña: cápsula de vidrio con borde violeta al enfocar. */
.login-dialog StEntry,
.unlock-dialog StEntry {
  background-color: rgba(4, 30, 27, 0.78);
  border: 1px solid rgba(207, 233, 221, 0.18);
  border-radius: 999px;
  color: #e6f2ec;
  selection-background-color: #7a5cf0;
  caret-color: #a48bff;
}
.login-dialog StEntry:focus,
.unlock-dialog StEntry:focus {
  border-color: rgba(164, 139, 255, 0.85);
}

/* Botones redondos de la pantalla (accesibilidad, sesión, siguiente). */
.login-dialog-button.a11y-button,
.login-dialog-button.cancel-button,
.login-dialog-button.switch-user-button,
.login-dialog-button.login-dialog-session-list-button {
  background-color: rgba(4, 30, 27, 0.72);
  border: 1px solid rgba(207, 233, 221, 0.14);
}

.login-dialog-banner,
.login-dialog-message,
.login-dialog-prompt-label,
.login-dialog-not-listed-label {
  color: rgba(207, 233, 221, 0.85);
}

/* Barra superior de la pantalla de inicio de sesión. */
#panel.login-screen,
#panel.unlock-screen {
  background-color: transparent;
}
"""


def main():
    names = subprocess.run(["gresource", "list", SOURCE], check=True, capture_output=True, text=True).stdout.split()
    work = tempfile.mkdtemp(prefix="argon-gdm-")
    try:
        files = []
        for res in names:
            rel = res[len(PREFIX):] if res.startswith(PREFIX) else None
            if not rel or rel.endswith(".xml"):
                continue
            data = subprocess.run(["gresource", "extract", SOURCE, res], check=True, capture_output=True).stdout
            path = os.path.join(work, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            files.append(rel)

        # gdm.css = estilos de Marble-argon (los del escritorio) + capa ARGON.
        with open(os.path.join(work, "gnome-shell-dark.css"), encoding="utf-8") as f:
            marble = f.read()
        with open(os.path.join(work, "gdm.css"), "w", encoding="utf-8") as f:
            f.write(marble + "\n" + ARGON_CSS)

        # Fondo: el humo desenfocado y algo más oscuro, para que la tarjeta se lea.
        bg = Image.open(BACKGROUND).convert("RGB")
        bg = bg.filter(ImageFilter.GaussianBlur(28))
        bg = ImageEnhance.Brightness(bg).enhance(0.72)
        bg.save(os.path.join(work, "argon-login.jpg"), quality=92)
        if "argon-login.jpg" not in files:
            files.append("argon-login.jpg")

        manifest = os.path.join(work, "argon.gresource.xml")
        with open(manifest, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<gresources>\n  <gresource prefix="/org/gnome/shell/theme">\n')
            for rel in sorted(files):
                f.write(f"    <file>{rel}</file>\n")
            f.write("  </gresource>\n</gresources>\n")

        os.makedirs(OUT_DIR, exist_ok=True)
        out = os.path.join(OUT_DIR, "gnome-shell-theme.gresource")
        subprocess.run(["glib-compile-resources", "--sourcedir", work, "--target", out, manifest], check=True)
        shutil.copy(os.path.join(work, "argon-login.jpg"), os.path.join(OUT_DIR, "vista-fondo-login.jpg"))
        print("listo:", out, f"({len(files)} archivos)")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
