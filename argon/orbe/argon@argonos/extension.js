// ARGON — orbe en el panel.
// Muestra el estado de Strata (apagado, cargado, pensando), la batería y si los equipos de tu flota
// están en la red. Solo lee estado; la única acción es cargar o descargar Strata con un clic.

import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Soup from 'gi://Soup?version=3.0';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {PlasmaAnimator} from './plasma.js';

const STRATA = 'http://127.0.0.1:8080';
const ARGOND = 'http://127.0.0.1:8737';
const APP_ID = 'dev.argon.Argon';
const TOKEN_PATH = GLib.build_filenamev([GLib.get_user_data_dir(), 'argon', 'token']);

const SHELL_IFACE = `<node><interface name="dev.argon.Shell">
  <method name="SwitchWorkspace"><arg type="i" direction="in" name="number"/></method>
</interface></node>`;

// Super + Espacio: si ARGON está al frente lo oculta; si no, lo abre o lo trae al frente.
function toggleArgonWindow() {
    const focused = global.display.focus_window;
    const isArgon = focused && (focused.get_gtk_application_id?.() === APP_ID || focused.get_wm_class() === APP_ID);
    if (isArgon) {
        Gio.DBus.session.call(APP_ID, '/dev/argon/Argon', 'org.gtk.Actions', 'Activate',
            new GLib.Variant('(sava{sv})', ['toggle', [], {}]), null, Gio.DBusCallFlags.NONE, 2000, null, null);
        return;
    }
    const app = Shell.AppSystem.get_default().lookup_app(`${APP_ID}.desktop`);
    if (app)
        app.activate();
    else
        Main.notify('ARGON', 'No encontré la app ARGON instalada.');
}
const POLL_SECONDS = 3;
const FLEET_EVERY = 10; // la flota se consulta cada 10 ciclos (~30 s)
// Equipos de tu red Tailscale que quieres ver en el menú. Se leen de ~/.config/argon/argon.json:
//   "flota": [{"label": "SERVIDOR", "dns": "servidor.", "note": "coordinador"}]
// Sin ese archivo, el menú no muestra flota.
function loadFleet() {
    try {
        const path = GLib.build_filenamev([GLib.get_user_config_dir(), 'argon', 'argon.json']);
        const [ok, bytes] = GLib.file_get_contents(path);
        const fleet = ok ? JSON.parse(new TextDecoder().decode(bytes)).flota : null;
        return Array.isArray(fleet) ? fleet.filter(n => n && n.label && n.dns) : [];
    } catch {
        return [];
    }
}
const FLEET = loadFleet();

const decoder = new TextDecoder();

function readSysfs(path) {
    try {
        const [ok, bytes] = GLib.file_get_contents(path);
        return ok ? decoder.decode(bytes).trim() : null;
    } catch {
        return null;
    }
}

const DOT_ON = '#3EE0A0';   // verde: en marcha / en la red
const DOT_OFF = '#5c6f68';  // gris: apagado / sin datos
const DOT_WARN = '#e7b85c'; // ámbar: fuera de la red

function setDotted(item, text, color) {
    const safe = GLib.markup_escape_text(text, -1);
    item.label.clutter_text.set_markup(`<span foreground="${color}">●</span>  ${safe}`);
}

function infoItem(text, styleClass = 'argon-detail') {
    const item = new PopupMenu.PopupMenuItem(text, {reactive: false, can_focus: false});
    item.label.add_style_class_name(styleClass);
    return item;
}

const ArgonOrb = GObject.registerClass(
class ArgonOrb extends PanelMenu.Button {
    _init(extension) {
        super._init(0.5, 'ARGON');
        this._ext = extension;
        this._session = new Soup.Session({timeout: 4});
        this._cancellable = new Gio.Cancellable();
        this._status = null;     // última respuesta de Strata, o null si no responde
        this._fleet = new Map(); // dns -> en línea
        this._onBattery = false;
        this._warnedBattery = false;
        this._breathing = false;
        this._tick = 0;

        const gicon = Gio.FileIcon.new(extension.dir.get_child('orb.png'));
        this._icon = new St.Icon({gicon, style_class: 'system-status-icon argon-orb'});
        this._desaturate = new Clutter.DesaturateEffect({factor: 1.0});
        this._icon.add_effect(this._desaturate);
        this.add_child(this._icon);
        this._plasma = new PlasmaAnimator(this._icon, extension.dir);

        this._buildMenu();
        this._poll();
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, POLL_SECONDS, () => {
            this._poll();
            return GLib.SOURCE_CONTINUE;
        });
        // Al cerrar sesión GNOME destruye el panel sin pasar por disable(): se cortan las consultas.
        this.connect('destroy', () => {
            this._cancellable.cancel();
            if (this._timer) {
                GLib.source_remove(this._timer);
                this._timer = null;
            }
        });
    }

    _buildMenu() {
        const title = infoItem('A R G O N', 'argon-title');
        this.menu.addMenuItem(title);
        const open = new PopupMenu.PopupMenuItem('Abrir ARGON   ·   Super + Espacio');
        open.connect('activate', () => toggleArgonWindow());
        this.menu.addMenuItem(open);
        this._tasksItem = infoItem('', 'popup-menu-item');
        this.menu.addMenuItem(this._tasksItem);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem('Strata'));
        this._strataState = infoItem('Consultando…', 'popup-menu-item');
        this._strataDetail = infoItem('');
        this.menu.addMenuItem(this._strataState);
        this.menu.addMenuItem(this._strataDetail);

        this._toggle = new PopupMenu.PopupMenuItem('');
        this._toggle.add_style_class_name('argon-action');
        this._toggle.connect('activate', () => this._toggleStrata());
        this.menu.addMenuItem(this._toggle);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem('Equipo'));
        this._battery = infoItem('', 'popup-menu-item');
        this.menu.addMenuItem(this._battery);

        if (FLEET.length)
            this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem('Flota'));
        this._fleetItems = FLEET.map(node => {
            const item = infoItem(`${node.label} · consultando…`, 'popup-menu-item');
            this.menu.addMenuItem(item);
            return item;
        });
    }

    // --- Consultas ---------------------------------------------------------

    _poll() {
        this._readBattery();
        this._request('GET', '/v1/status', null, (code, body) => {
            this._status = code === 200 ? body : null;
            this._render();
        });
        this._readTasks();
        if (this._tick++ % FLEET_EVERY === 0 && FLEET.length)
            this._readFleet();
    }

    _readTasks() {
        // Estado de argond: cuántos pedidos están pensando, trabajando o esperando tu confirmación.
        let token = '';
        try {
            token = decoder.decode(GLib.file_get_contents(TOKEN_PATH)[1]).trim();
        } catch {
            // Sin clave todavía: argond no ha arrancado nunca.
        }
        this._request('GET', '/status', null, (code, body) => {
            this._tasks = code === 200 ? body : null;
            const t = this._tasks;
            if (!t) {
                setDotted(this._tasksItem, 'Tareas · el servicio ARGON no responde', DOT_WARN);
            } else {
                const busy = t.thinking + t.running;
                const parts = [];
                if (busy)
                    parts.push(`${busy} trabajando`);
                if (t.waiting)
                    parts.push(`${t.waiting} esperando tu confirmación`);
                setDotted(this._tasksItem, `Tareas · ${parts.join(' · ') || 'nada en curso'}`, busy ? DOT_ON : DOT_OFF);
            }
            this._render();
        }, ARGOND, token);
    }

    _request(method, path, payload, callback, base = STRATA, token = null) {
        const msg = Soup.Message.new(method, `${base}${path}`);
        if (token)
            msg.get_request_headers().append('X-Argon-Token', token);
        if (payload !== null) {
            const bytes = new GLib.Bytes(new TextEncoder().encode(JSON.stringify(payload)));
            msg.set_request_body_from_bytes('application/json', bytes);
        }
        this._session.send_and_read_async(msg, GLib.PRIORITY_DEFAULT, this._cancellable, (session, res) => {
            let body = null;
            let code = 0;
            try {
                const bytes = session.send_and_read_finish(res);
                code = msg.get_status();
                body = JSON.parse(decoder.decode(bytes.get_data()));
            } catch {
                // Strata apagado o respuesta no JSON: se trata como sin respuesta.
            }
            if (!this._cancellable.is_cancelled())
                callback(code, body);
        });
    }

    _readBattery() {
        const online = readSysfs('/sys/class/power_supply/ACAD/online');
        const capacity = readSysfs('/sys/class/power_supply/BAT1/capacity');
        const onBattery = online === '0';
        if (onBattery && !this._onBattery)
            this._warnedBattery = false;
        this._onBattery = onBattery;
        const where = onBattery ? 'con batería' : 'enchufada';
        this._battery.label.text = capacity ? `Batería ${capacity}% · ${where}` : `Energía · ${where}`;
    }

    _readFleet() {
        try {
            const proc = Gio.Subprocess.new(['tailscale', 'status', '--json'],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            proc.communicate_utf8_async(null, this._cancellable, (p, res) => {
                try {
                    const [, out] = p.communicate_utf8_finish(res);
                    const peers = Object.values(JSON.parse(out).Peer ?? {});
                    for (const node of FLEET) {
                        const peer = peers.find(x => (x.DNSName ?? '').startsWith(node.dns));
                        this._fleet.set(node.dns, peer ? Boolean(peer.Online) : null);
                    }
                } catch {
                    FLEET.forEach(node => this._fleet.set(node.dns, null));
                }
                this._renderFleet();
            });
        } catch {
            FLEET.forEach(node => this._fleet.set(node.dns, null));
            this._renderFleet();
        }
    }

    // --- Dibujo ------------------------------------------------------------

    _render() {
        const s = this._status;
        if (!s) {
            this._setOrb('off');
            setDotted(this._strataState, 'Strata · apagado', DOT_OFF);
            this._strataDetail.label.text = 'Ábrelo con el ícono STRATA del dock';
            this._toggle.visible = false;
            return;
        }

        const thinking = (s.activity?.in_flight ?? 0) > 0;
        const gpu = s.machine?.gpu;
        const vram = gpu ? `GPU ${(gpu.used_mib / 1024).toFixed(1)}/${(gpu.total_mib / 1024).toFixed(1)} GB` : '';
        const temp = gpu?.temp_c != null ? ` · ${Math.round(gpu.temp_c)} °C` : '';
        const watts = gpu?.power_w != null ? ` · ${Math.round(gpu.power_w)} W` : '';

        if (!s.loaded) {
            this._setOrb('idle-unloaded');
            setDotted(this._strataState, 'Strata · modelo descargado', DOT_OFF);
            this._strataDetail.label.text = 'La tarjeta gráfica está libre';
        } else {
            const argonBusy = this._tasks ? this._tasks.thinking + this._tasks.running > 0 : false;
            this._setOrb(thinking || argonBusy ? 'thinking' : 'ready');
            setDotted(this._strataState, thinking ? 'Strata · pensando…' : 'Strata · listo', DOT_ON);
            this._strataDetail.label.text = `${s.model} · ${vram}${temp}${watts}`;
        }

        this._toggle.visible = !thinking;
        this._toggle.label.text = s.loaded
            ? 'Liberar la tarjeta gráfica (descargar Strata)'
            : 'Cargar Strata';

        if (this._onBattery && s.loaded && !this._warnedBattery) {
            this._warnedBattery = true;
            Main.notify('ARGON',
                'Estás con batería y Strata ocupa la tarjeta gráfica. Puedes descargarlo desde el orbe del panel.');
        }
    }

    _renderFleet() {
        FLEET.forEach((node, i) => {
            const online = this._fleet.get(node.dns);
            const known = online !== null && online !== undefined;
            const state = !known ? 'sin datos' : online ? 'en la red' : 'fuera de la red';
            const color = !known ? DOT_OFF : online ? DOT_ON : DOT_WARN;
            setDotted(this._fleetItems[i], `${node.label} · ${state} · ${node.note}`, color);
        });
    }

    _setOrb(state) {
        // off: gris y quieto · idle-unloaded: tenue y quieto · ready: plasma lento · thinking: plasma rápido.
        // Con batería, el plasma solo se mueve mientras Strata piensa.
        this._desaturate.factor = state === 'off' ? 1.0 : 0.0;
        this._icon.opacity = state === 'off' ? 110 : state === 'idle-unloaded' ? 150 : 255;
        let fps = 0;
        if (state === 'thinking')
            fps = 20;
        else if (state === 'ready' && !this._onBattery)
            fps = 8;
        this._plasma.play(fps);
    }

    // --- Acción ------------------------------------------------------------

    _toggleStrata() {
        const s = this._status;
        if (!s)
            return;
        const [path, payload, done] = s.loaded
            ? ['/v1/unload', {}, 'Strata descargado: la tarjeta gráfica quedó libre.']
            : ['/v1/load', {model: s.model}, 'Cargando Strata…'];
        this._request('POST', path, payload, code => {
            if (code === 200)
                Main.notify('ARGON', done);
            else if (code === 409)
                Main.notify('ARGON', 'Strata está ocupado. Inténtalo cuando termine de responder.');
            else if (code === 401)
                Main.notify('ARGON', 'Strata pidió una clave para esta acción. Hazlo desde su propia ventana.');
            else
                Main.notify('ARGON', `Strata no aceptó la acción (código ${code}).`);
            this._poll();
        });
    }

    destroy() {
        this._cancellable.cancel();
        if (this._timer) {
            GLib.source_remove(this._timer);
            this._timer = null;
        }
        this._plasma.destroy();
        this._session.abort();
        super.destroy();
    }
});

export default class ArgonExtension extends Extension {
    enable() {
        Main.wm.addKeybinding('command-bar-shortcut', this.getSettings(), Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW, () => toggleArgonWindow());
        // argond le pide a GNOME lo que solo GNOME puede hacer (cambiar de escritorio virtual).
        this._dbus = Gio.DBusExportedObject.wrapJSObject(SHELL_IFACE, {
            SwitchWorkspace(number) {
                const ws = global.workspace_manager.get_workspace_by_index(number - 1);
                if (!ws)
                    throw new Error(`No existe el escritorio ${number}.`);
                ws.activate(global.get_current_time());
            },
        });
        this._dbus.export(Gio.DBus.session, '/dev/argon/Shell');
        this._nameId = Gio.bus_own_name_on_connection(Gio.DBus.session, 'dev.argon.Shell',
            Gio.BusNameOwnerFlags.NONE, null, null);
        this._orb = new ArgonOrb(this);
        Main.panel.addToStatusArea(this.uuid, this._orb, 0, 'right');
    }

    disable() {
        Main.wm.removeKeybinding('command-bar-shortcut');
        if (this._nameId) {
            Gio.bus_unown_name(this._nameId);
            this._nameId = 0;
        }
        this._dbus?.unexport();
        this._dbus = null;
        this._orb?.destroy();
        this._orb = null;
    }
}
