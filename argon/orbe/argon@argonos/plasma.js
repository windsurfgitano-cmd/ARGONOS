// ARGON — anima un St.Icon recorriendo los cuadros del orbe de plasma (orb-frames/orb-NNN.png).
// Solo cambia el ícono: no usa la GPU para nada más, y se detiene del todo cuando no hace falta.

import GLib from 'gi://GLib';
import Gio from 'gi://Gio';

export class PlasmaAnimator {
    constructor(icon, extensionDir) {
        this._icon = icon;
        this._timer = 0;
        this._index = 0;
        this._fps = 0;
        const dir = extensionDir.get_child('orb-frames');
        this._frames = [];
        for (let i = 0; i < 1000; i++) {
            const file = dir.get_child(`orb-${String(i).padStart(3, '0')}.png`);
            if (!file.query_exists(null))
                break;
            this._frames.push(Gio.FileIcon.new(file));
        }
        if (this._frames.length === 0)
            this._frames.push(Gio.FileIcon.new(extensionDir.get_child('orb.png')));
        this._icon.gicon = this._frames[0];
        // Si GNOME destruye el ícono (por ejemplo al cerrar sesión), la animación se detiene sola.
        this._icon.connect('destroy', () => this.destroy());
    }

    // fps = 0 detiene la animación y deja el primer cuadro.
    play(fps) {
        if (fps === this._fps)
            return;
        this._stopTimer();
        this._fps = fps;
        if (fps <= 0 || this._frames.length < 2) {
            this._index = 0;
            this._icon.gicon = this._frames[0];
            return;
        }
        this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, Math.round(1000 / fps), () => {
            this._index = (this._index + 1) % this._frames.length;
            this._icon.gicon = this._frames[this._index];
            return GLib.SOURCE_CONTINUE;
        });
    }

    _stopTimer() {
        if (this._timer) {
            GLib.source_remove(this._timer);
            this._timer = 0;
        }
    }

    destroy() {
        this._stopTimer();
        this._fps = 0;
    }
}
