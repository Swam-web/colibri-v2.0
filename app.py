#!/usr/bin/env python3
"""Colibri v2.0 Launcher - GUI GTK moderne pour telecharger, builder et lancer
les modeles colibri sans toucher au terminal. Style cartes + mode sombre.
Base moteur : JustVugg/colibri (upstream, licence d'origine conservee)."""
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Notify", "0.7")
try:
    gi.require_version("Vte", "2.91")
    from gi.repository import Vte
    HAS_VTE = True
except (ImportError, ValueError):
    Vte = None
    HAS_VTE = False
from gi.repository import Gtk, GLib, Pango, Notify

APP_NAME = "colibri-launcher"
CONF_DIR = os.path.join(os.path.expanduser("~"), ".config", "colibri-launcher")
CONF_FILE = os.path.join(CONF_DIR, "config.json")
SESS_FILE = os.path.join(CONF_DIR, "sessions.json")
HF_BIN_CANDIDATES = [
    os.path.expanduser("~/.local/bin/hf"),
    os.path.expanduser("~/.hermes/bin/uvx"),
    "hf",
]

MODELS = [
    {"id": "qwen38", "name": "Qwen3.8-Flash", "params": "125B + 51B MoE",
     "size": "185 Go", "repo": "Qwen/Qwen3.8-Flash-Next-FP8",
     "rev": "bcd9f01ddc9cff2316eb84281bebcd5b058bddce",
     "target": "qwen38", "kind": "direct",
     "notes": "Testé OK sur i9-14900K (~2 tok/s). Tool calling + vision."},
    {"id": "glm53flash", "name": "GLM-5.3-Flash", "params": "321B MoE + vision",
     "size": "~195 Go convertis", "repo": "zai-org/GLM-5.3-Flash",
     "rev": "", "target": "glm53", "kind": "convert",
     "notes": "Conversion 25h : tools/convert_glm53.py. Lent au decode."},
    {"id": "dsv41", "name": "DeepSeek V4.1-Flash", "params": "552B MoE + vision",
     "size": "510 Go", "repo": "deepseek-ai/DeepSeek-V4.1-Flash",
     "rev": "", "target": "deepseek_v41", "kind": "sidecar",
     "notes": "+ prepare_dsv41.py (sidecar 1 Mo). Drafting MTP intégré."},
    {"id": "dsv4", "name": "DeepSeek V4-Flash", "params": "284B MoE",
     "size": "~290 Go", "repo": "deepseek-ai/DeepSeek-V4-Flash",
     "rev": "", "target": "deepseek-v4", "kind": "direct",
     "notes": "Petit frere du V4.1."},
    {"id": "qwen36", "name": "Qwen3.6", "params": "35B-A3B MoE",
     "size": "~70 Go", "repo": "", "rev": "", "target": "qwen36",
     "kind": "direct", "notes": "Compact, bon candidat fluidite."},
    {"id": "olmoe", "name": "OLMoE", "params": "7B MoE",
     "size": "~7 Go", "repo": "", "rev": "", "target": "olmoe",
     "kind": "direct", "notes": "Tient en RAM : le plus fluide."},
    {"id": "glm52", "name": "GLM-5.2", "params": "744B MoE",
     "size": "372 Go NVMe", "repo": "", "rev": "", "target": "glm",
     "kind": "convert", "notes": "Gros : 372 Go sur NVMe."},
    {"id": "inkling", "name": "Inkling", "params": "975B MoE",
     "size": "~500 Go+", "repo": "", "rev": "", "target": "inkling",
     "kind": "direct", "notes": "Enorme, pour tres grosses configs."},
    {"id": "k3", "name": "Kimi K3", "params": "2.8T MoE",
     "size": "~1.6 To", "repo": "", "rev": "", "target": "kimi_k3",
     "kind": "direct", "notes": "Le plus gros. Non teste ici."},
]


def load_conf():
    d = {"colibri_dir": "/home/christophe/colibri", "models_dir": "/mnt/DATA/Models",
         "dark": True, "ctx": 8192, "cap": 43, "ngen": 128, "port": 8000}
    try:
        with open(CONF_FILE) as f:
            d.update(json.load(f))
    except (FileNotFoundError, ValueError):
        pass
    return d


def save_conf(d):
    try:
        os.makedirs(CONF_DIR, exist_ok=True)
        with open(CONF_FILE, "w") as f:
            json.dump(d, f, indent=2)
    except OSError:
        pass


def load_sessions():
    d = {"current": None, "sessions": []}
    try:
        with open(SESS_FILE) as f:
            d.update(json.load(f))
    except (FileNotFoundError, ValueError):
        pass
    return d


def save_sessions(d):
    try:
        os.makedirs(CONF_DIR, exist_ok=True)
        with open(SESS_FILE, "w") as f:
            json.dump(d, f, indent=2)
    except OSError:
        pass


def msg_text(m):
    """Texte affichable d'un message (l'image devient 🖼 [image])."""
    c = m.get("content", "")
    if isinstance(c, str):
        return c
    parts = []
    for p in c:
        if not isinstance(p, dict):
            continue
        if p.get("type") == "text":
            parts.append(p.get("text", ""))
        elif p.get("type") == "image_url":
            u = p.get("image_url", {}).get("url", "") if isinstance(p.get("image_url"), dict) else ""
            parts.append(f"🖼 [image: {os.path.basename(u)}]" if u else "🖼 [image]")
    return "\n".join(parts)


def run_cmd(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()
    except FileNotFoundError:
        return False, "introuvable"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def find_hf():
    for c in HF_BIN_CANDIDATES:
        if c.endswith("uvx"):
            if os.path.isfile(os.path.expanduser(c)):
                return [os.path.expanduser(c), "--from", "huggingface_hub", "hf"]
        elif shutil.which(c):
            return [c]
    return None


def dir_size_gb(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total / 1e9


class Launcher(Gtk.Window):
    def __init__(self):
        super().__init__(title="Colibri v2.0 Launcher")
        self.conf = load_conf()
        Gtk.Settings.get_default().set_property(
            "gtk-application-prefer-dark-theme", bool(self.conf.get("dark", True)))
        self.set_default_size(1020, 700)
        self.set_border_width(10)
        self.serve_proc = None
        self.worker = None

        Notify.init(APP_NAME)

        # Style bulles de chat : séparation bien visible (user teinté, assistant neutre)
        css = Gtk.CssProvider()
        css.load_from_data(b"""
        .chat-row { border-bottom: 1px solid alpha(currentColor, 0.18); }
        .chat-user { background: alpha(@theme_selected_bg_color, 0.14);
                     border-left: 3px solid @theme_selected_bg_color; }
        .chat-assistant { border-left: 3px solid alpha(currentColor, 0.35); }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        hb = Gtk.HeaderBar(title="Colibri v2.0 Launcher", subtitle="fork communautaire — moteur JustVugg/colibri")
        hb.set_show_close_button(True)
        self.set_titlebar(hb)
        self.dark_btn = Gtk.ToggleButton(label="🌙", active=bool(self.conf.get("dark", True)))
        self.dark_btn.set_tooltip_text("Mode sombre")
        self.dark_btn.connect("toggled", self.on_dark)
        hb.pack_end(self.dark_btn)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(vbox)
        self.status = Gtk.Label(label="Prêt.", xalign=0)
        self.status.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        vbox.pack_start(self.status, False, False, 0)

        nb = Gtk.Notebook()
        vbox.pack_start(nb, True, True, 0)
        nb.append_page(self.page_models(), Gtk.Label(label="Modèles"))
        nb.append_page(self.page_engine(), Gtk.Label(label="Moteur"))
        nb.append_page(self.page_run(), Gtk.Label(label="Lancer"))
        nb.append_page(self.page_chat(), Gtk.Label(label="Chat"))
        nb.append_page(self.page_sys(), Gtk.Label(label="Système"))

        # Console
        frame = Gtk.Frame(label="Console")
        frame.set_shadow_type(Gtk.ShadowType.IN)
        self.logview = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD)
        sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        sw.set_min_content_height(150)
        sw.add(self.logview)
        frame.add(sw)
        vbox.pack_start(frame, False, False, 0)
        self.log("Bienvenue. Dossiers : colibri=%s modèles=%s" %
                 (self.conf["colibri_dir"], self.conf["models_dir"]))

    # ---------- utilitaires ----------
    def log(self, msg):
        buf = self.logview.get_buffer()
        buf.insert(buf.get_end_iter(), time.strftime("[%H:%M:%S] ") + msg + "\n")
        GLib.idle_add(lambda: self.logview.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0))

    def notify(self, msg):
        try:
            Notify.Notification.new("Colibri v2.0", msg, "dialog-information").show()
        except Exception:
            pass
        self.status.set_text(msg)

    def on_dark(self, btn):
        dark = btn.get_active()
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", dark)
        self.conf["dark"] = dark
        save_conf(self.conf)

    def coli(self):
        return os.path.join(self.conf["colibri_dir"], "c", "coli")

    def model_dir(self, m):
        return os.path.join(self.conf["models_dir"], m["repo"].split("/")[-1] if m["repo"] else m["id"])

    def local_status(self, m):
        d = self.model_dir(m)
        if not os.path.isdir(d):
            return "⬜ absent"
        n = len([f for f in os.listdir(d) if f.endswith(".safetensors")])
        gb = dir_size_gb(d)
        if n:
            return f"🟩 {n} shards · {gb:.0f} Go"
        return f"🟨 dossier ({gb:.1f} Go)"

    # ---------- onglet Modèles ----------
    def page_models(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=12)
        paths = Gtk.Grid(column_spacing=8, row_spacing=6)
        paths.attach(Gtk.Label(label="Colibri :"), 0, 0, 1, 1)
        self.e_coli = Gtk.Entry(text=self.conf["colibri_dir"])
        self.e_coli.set_hexpand(True)
        paths.attach(self.e_coli, 1, 0, 1, 1)
        paths.attach(Gtk.Label(label="Modèles :"), 0, 1, 1, 1)
        self.e_models = Gtk.Entry(text=self.conf["models_dir"])
        self.e_models.set_hexpand(True)
        paths.attach(self.e_models, 1, 1, 1, 1)
        b_paths = Gtk.Button(label="Appliquer dossiers")
        b_paths.connect("clicked", self.on_paths)
        paths.attach(b_paths, 1, 2, 1, 1)
        box.pack_start(paths, False, False, 0)

        self.model_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        sw.set_min_content_height(280)
        sw.add(self.model_list)
        frame = Gtk.Frame(label="Familles supportées")
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame.add(sw)
        box.pack_start(frame, True, True, 0)

        h = Gtk.Box(spacing=6, homogeneous=True)
        for label, fn in [("⬇ Télécharger", self.ui_download),
                          ("🔨 Builder moteur", self.ui_build),
                          ("🗑 Supprimer poids", self.ui_delete)]:
            b = Gtk.Button(label=label)
            b.connect("clicked", fn)
            h.pack_start(b, True, True, 0)
        box.pack_start(h, False, False, 0)
        self.refresh_models()
        return box

    def on_paths(self, *_):
        self.conf["colibri_dir"] = self.e_coli.get_text().strip()
        self.conf["models_dir"] = self.e_models.get_text().strip()
        save_conf(self.conf)
        self.refresh_models()
        self.log("Dossiers mis à jour.")

    def selected_model(self):
        row = self.model_list.get_selected_row()
        return getattr(row, "model", None) if row else None

    def refresh_models(self):
        for ch in self.model_list.get_children():
            self.model_list.remove(ch)
        for m in MODELS:
            row = Gtk.ListBoxRow()
            h = Gtk.Box(spacing=10, margin=8)
            h.pack_start(Gtk.Label(label=f"<b>{m['name']}</b>", use_markup=True, width_chars=20, xalign=0), False, False, 0)
            h.pack_start(Gtk.Label(label=f"<tt>{m['params']}</tt>", use_markup=True, width_chars=18, xalign=0), False, False, 0)
            h.pack_start(Gtk.Label(label=m["size"], width_chars=16, xalign=0), False, False, 0)
            h.pack_start(Gtk.Label(label=m["notes"], xalign=0, ellipsize=Pango.EllipsizeMode.END), True, True, 0)
            h.pack_end(Gtk.Label(label=self.local_status(m), width_chars=22, xalign=1), False, False, 0)
            row.add(h)
            row.model = m
            self.model_list.add(row)
        self.model_list.show_all()

    def busy(self, msg):
        self.notify(msg)
        return msg

    def ui_download(self, *_):
        m = self.selected_model()
        if not m:
            self.notify("Sélectionne un modèle d'abord.")
            return
        if not m["repo"]:
            self.notify(f"{m['name']} : repo HF à renseigner (famille non documentée ici).")
            return
        hf = find_hf()
        if not hf:
            self.notify("Client HF introuvable (ni hf, ni uvx).")
            return
        dest = self.model_dir(m)
        os.makedirs(dest, exist_ok=True)
        cmd = hf + ["download", m["repo"]] + (["--revision", m["rev"]] if m["rev"] else []) + ["--local-dir", dest]
        self.busy(f"Téléchargement {m['name']} → {dest} (fond, voir Console)...")
        self.log("$ " + " ".join(cmd))
        self.run_worker(cmd, done_msg=f"{m['name']} téléchargé.", refresh=True)

    def ui_build(self, *_):
        m = self.selected_model()
        if not m:
            self.notify("Sélectionne un modèle d'abord.")
            return
        cmd = ["make", "-C", os.path.join(self.conf["colibri_dir"], "c"), m["target"]]
        self.busy(f"Build moteur {m['target']}...")
        self.log("$ " + " ".join(cmd))
        self.run_worker(cmd, done_msg=f"Moteur {m['target']} buildé.")

    def ui_delete(self, *_):
        m = self.selected_model()
        if not m:
            return
        d = self.model_dir(m)
        dlg = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.OK_CANCEL,
                                text=f"Supprimer {d} ?")
        if dlg.run() == Gtk.ResponseType.OK:
            import shutil as _sh
            try:
                _sh.rmtree(d)
                self.log(f"Supprimé : {d}")
            except OSError as e:
                self.log(f"Erreur suppression : {e}")
            self.refresh_models()
        dlg.destroy()

    def run_worker(self, cmd, done_msg, refresh=False):
        if self.worker and self.worker.is_alive():
            self.notify("Une tâche tourne déjà, attends la fin.")
            return

        def work():
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in p.stdout:
                    GLib.idle_add(self.log, line.rstrip()[-300:])
                p.wait()
                if p.returncode == 0:
                    GLib.idle_add(self.notify, done_msg)
                    if refresh:
                        GLib.idle_add(self.refresh_models)
                else:
                    GLib.idle_add(self.notify, f"Échec (code {p.returncode}), voir Console.")
            except Exception as e:
                GLib.idle_add(self.notify, f"Erreur : {e}")

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    # ---------- onglet Moteur ----------
    def page_engine(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=12)
        frame = Gtk.Frame(label="Binaires (c/)")
        frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        self.eng_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.set_min_content_height(200)
        sw.add(self.eng_list)
        frame.add(sw)
        box.pack_start(frame, True, True, 0)
        h = Gtk.Box(spacing=6, homogeneous=True)
        b_refresh = Gtk.Button(label="↻ Actualiser")
        b_refresh.connect("clicked", lambda *_: self.refresh_engines())
        b_check = Gtk.Button(label="✓ make check (cible par défaut)")
        b_check.connect("clicked", lambda *_: self.run_worker(
            ["make", "-C", os.path.join(self.conf["colibri_dir"], "c"), "check"],
            "make check terminé."))
        h.pack_start(b_refresh, True, True, 0)
        h.pack_start(b_check, True, True, 0)
        box.pack_start(h, False, False, 0)
        self.refresh_engines()
        return box

    def refresh_engines(self):
        for ch in self.eng_list.get_children():
            self.eng_list.remove(ch)
        cdir = os.path.join(self.conf["colibri_dir"], "c")
        for m in MODELS:
            bpath = os.path.join(cdir, m["target"])
            ok = os.path.isfile(bpath) and os.access(bpath, os.X_OK)
            row = Gtk.ListBoxRow()
            h = Gtk.Box(spacing=10, margin=8)
            h.pack_start(Gtk.Label(label="🟩" if ok else "⬜"), False, False, 0)
            h.pack_start(Gtk.Label(label=f"<b><tt>{m['target']}</tt></b>", use_markup=True, width_chars=16, xalign=0), False, False, 0)
            h.pack_start(Gtk.Label(label=m["name"], xalign=0), True, True, 0)
            self.eng_list.add(row)
        self.eng_list.show_all()

    # ---------- onglet Lancer ----------
    def page_run(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=12)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        grid.attach(Gtk.Label(label="ctx :"), 0, 0, 1, 1)
        self.e_ctx = Gtk.Entry(text=str(self.conf.get("ctx", 8192)))
        self.e_ctx.set_width_chars(8)
        grid.attach(self.e_ctx, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="cap :"), 2, 0, 1, 1)
        self.e_cap = Gtk.Entry(text=str(self.conf.get("cap", 43)))
        self.e_cap.set_width_chars(6)
        grid.attach(self.e_cap, 3, 0, 1, 1)
        grid.attach(Gtk.Label(label="ngen :"), 4, 0, 1, 1)
        self.e_ngen = Gtk.Entry(text=str(self.conf.get("ngen", 128)))
        self.e_ngen.set_width_chars(6)
        grid.attach(self.e_ngen, 5, 0, 1, 1)
        grid.attach(Gtk.Label(label="port :"), 0, 1, 1, 1)
        self.e_port = Gtk.Entry(text=str(self.conf.get("port", 8000)))
        self.e_port.set_width_chars(8)
        grid.attach(self.e_port, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label="think :"), 2, 1, 1, 1)
        self.c_think = Gtk.ComboBoxText()
        for t in ["no-think", "low", "medium", "high"]:
            self.c_think.append_text(t)
        self.c_think.set_active(0)
        grid.attach(self.c_think, 3, 1, 2, 1)
        box.pack_start(grid, False, False, 0)

        h = Gtk.Box(spacing=6, homogeneous=True)
        for label, fn in [("💬 Chat (terminal)", self.ui_chat),
                          ("▶ Serve", self.ui_serve),
                          ("⏹ Stop serve", self.ui_stop),
                          ("🌐 Ouvrir Web", self.ui_web),
                          ("🩺 Plan", self.ui_plan),
                          ("🩺 Doctor", self.ui_doctor)]:
            b = Gtk.Button(label=label)
            b.connect("clicked", fn)
            h.pack_start(b, True, True, 0)
        box.pack_start(h, False, False, 0)
        h2 = Gtk.Box(spacing=6, homogeneous=True)
        b_oc = Gtk.Button(label="🔌 Connecter Opencode")
        b_oc.set_tooltip_text("Serve vérifié + provider colibri-local ajouté à opencode.jsonc (backup)")
        b_oc.connect("clicked", lambda *_: self.ui_link_opencode())
        h2.pack_start(b_oc, True, True, 0)
        b_he = Gtk.Button(label="🔌 Connecter Hermes")
        b_he.set_tooltip_text("Serve vérifié + snippet YAML à coller (schéma non documenté : pas d'écriture auto)")
        b_he.connect("clicked", lambda *_: self.ui_link_hermes())
        h2.pack_start(b_he, True, True, 0)
        box.pack_start(h2, False, False, 0)
        box.pack_start(Gtk.Label(label="Chat ouvre un terminal GNOME. Serve tourne en fond (bouton Stop pour couper).",
                                 xalign=0), False, False, 0)
        return box

    def run_params(self):
        m = self.selected_model()
        if not m:
            self.notify("Sélectionne un modèle (onglet Modèles) d'abord.")
            return None, None
        for k, e in (("ctx", self.e_ctx), ("cap", self.e_cap),
                     ("ngen", self.e_ngen), ("port", self.e_port)):
            self.conf[k] = e.get_text().strip()
        save_conf(self.conf)
        return m, self.model_dir(m)

    def ui_chat(self, *_):
        m, d = self.run_params()
        if not m:
            return
        think = [] if self.c_think.get_active_text() == "no-think" else ["--effort", self.c_think.get_active_text()]
        cmd = ["gnome-terminal", "--", self.coli(), "chat", "--model", d,
               "--ctx", self.conf["ctx"], "--cap", self.conf["cap"],
               "--ngen", self.conf["ngen"]] + think
        self.log("$ " + " ".join(cmd))
        try:
            subprocess.Popen(cmd)
        except FileNotFoundError:
            self.notify("gnome-terminal introuvable.")

    def ui_serve(self, *_):
        m, d = self.run_params()
        if not m:
            return
        if self.serve_proc and self.serve_proc.poll() is None:
            self.notify("Serve déjà en cours (Stop d'abord).")
            return
        cmd = [self.coli(), "serve", "--model", d, "--ctx", self.conf["ctx"],
               "--cap", self.conf["cap"], "--port", self.conf["port"]]
        self.log("$ " + " ".join(cmd))
        try:
            self.serve_proc = subprocess.Popen(cmd)
            self.notify(f"Serve lancé sur :{self.conf['port']} (Stop pour couper).")
        except Exception as e:
            self.notify(f"Erreur serve : {e}")

    def ui_stop(self, *_):
        if self.serve_proc and self.serve_proc.poll() is None:
            self.serve_proc.terminate()
            self.notify("Serve stoppé.")
        else:
            ok, out = run_cmd([self.coli(), "stop"], timeout=20)
            self.log(out[-500:] if out else "stop OK")
            self.notify("Stop envoyé.")

    def ui_web(self, *_):
        url = f"http://127.0.0.1:{self.e_port.get_text().strip()}/"
        subprocess.Popen(["xdg-open", url])
        self.log(f"Ouverture {url} (pense à lancer Serve d'abord).")

    def ui_plan(self, *_):
        m, d = self.run_params()
        if not m:
            return
        self.run_worker([self.coli(), "plan", "--model", d, "--ram", "26",
                         "--ctx", self.conf["ctx"], "--gpu", "none"], "Plan terminé.")

    def ui_doctor(self, *_):
        m, d = self.run_params()
        if not m:
            return
        self.run_worker([self.coli(), "doctor", "--model", d], "Doctor terminé.")

    def _serve_model_id(self):
        """Id du modèle servi (None si serve injoignable)."""
        import urllib.request
        try:
            with urllib.request.urlopen(self.serve_base() + "/v1/models", timeout=5) as r:
                data = json.loads(r.read().decode())
            models = data.get("data", [])
            if models:
                return models[0].get("id")
        except Exception as e:
            self.log(f"/v1/models injoignable : {e}")
        return None

    def ui_link_opencode(self):
        m, _d = self.run_params()
        if not m:
            return
        mid = self._serve_model_id()
        if not mid:
            self.notify("Serve injoignable : lance ▶ Serve d'abord.")
            return
        cfg_path = os.path.expanduser("~/.config/opencode/opencode.jsonc")
        try:
            with open(cfg_path) as f:
                raw = f.read()
            cfg = json.loads(raw) if raw.strip() else {}
        except (OSError, ValueError) as e:
            self.notify(f"opencode.jsonc illisible ({e}) : rien écrit.")
            return
        try:
            bak = cfg_path + ".bak-colibri"
            with open(bak, "w") as f:
                f.write(raw)
            prov = cfg.setdefault("provider", {})
            prov["colibri-local"] = {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Colibri v2.0 (local)",
                "options": {"baseURL": self.serve_base() + "/v1"},
                "models": {mid: {"name": f"{m['name']} (local)"}},
            }
            with open(cfg_path, "w") as f:
                json.dump(cfg, f, indent=2)
            self.log(f"Opencode branché : provider colibri-local → {mid} (backup {bak})")
            self.notify("Opencode connecté : choisis colibri-local dans /models.")
        except OSError as e:
            self.notify(f"Écriture impossible : {e}")

    def ui_link_hermes(self):
        m, _d = self.run_params()
        if not m:
            return
        mid = self._serve_model_id()
        if not mid:
            self.notify("Serve injoignable : lance ▶ Serve d'abord.")
            return
        cfg_path = os.path.expanduser("~/.hermes/config.yaml")
        try:
            bak = cfg_path + ".bak-colibri"
            import shutil as _sh
            _sh.copy2(cfg_path, bak)
        except OSError as e:
            self.notify(f"Backup Hermes impossible ({e}) : rien fait.")
            return
        snippet = (f"# Colibri v2.0 local ({m['name']}) — colle sous 'model:'\n"
                   f"# provider: colibri-local\n"
                   f"# base_url: {self.serve_base()}/v1\n"
                   f"# default: {mid}\n"
                   f"# (backup : {bak})")
        Gtk.Clipboard.get_default(self.get_display()).set_text(snippet, -1)
        self.log("Snippet Hermes copié (schéma custom non documenté : collage manuel) :\n" + snippet)
        dlg = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.INFO,
                                buttons=Gtk.ButtonsType.OK,
                                text="Snippet copié + backup fait.\nColle-le dans ~/.hermes/config.yaml (section model), "
                                     "adapte 'provider' selon ta version d'Hermes.")
        dlg.run()
        dlg.destroy()

    # ---------- onglet Chat style opencode (dialogue haut, saisie bas) ----------
    def page_chat(self):
        import urllib.request
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)

        # Barre sessions persistantes (comme opencode : on retrouve tout au relancement)
        sess = Gtk.Box(spacing=6)
        sess.pack_start(Gtk.Label(label="Session :"), False, False, 0)
        self.sess_combo = Gtk.ComboBoxText()
        self.sess_combo.set_hexpand(True)
        self.sess_combo.connect("changed", lambda *_: self.ui_sess_switch())
        sess.pack_start(self.sess_combo, True, True, 0)
        b_new_top = Gtk.Button(label="🧹 Nouvelle")
        b_new_top.connect("clicked", lambda *_: self.ui_chat_new())
        sess.pack_start(b_new_top, False, False, 0)
        b_del_top = Gtk.Button(label="🗑 Supprimer")
        b_del_top.set_tooltip_text("Supprimer la session affichée")
        b_del_top.connect("clicked", lambda *_: self.ui_sess_delete())
        sess.pack_start(b_del_top, False, False, 0)
        box.pack_start(sess, False, False, 0)

        # Grande fenêtre : dialogue
        self.chat_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        sw.set_min_content_height(420)
        sw.add(self.chat_list)
        frame = Gtk.Frame(label="Dialogue")
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame.add(sw)
        box.pack_start(frame, True, True, 0)
        self.chat_sw = sw
        self.chat_history = []   # [{"role":..,"content":..}] pour le contexte multi-tours
        self.chat_busy = False
        self.chat_abort = False
        self.chat_image = None

        # Petite fenêtre : saisie
        comp = Gtk.Frame(label="Message")
        comp.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        cv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        self.chat_entry = Gtk.Entry(placeholder_text="Écris ton message... (Entrée pour envoyer)")
        self.chat_entry.connect("activate", lambda *_: self.ui_chat_send())
        cv.pack_start(self.chat_entry, False, False, 0)
        h = Gtk.Box(spacing=6)
        self.chat_img_label = Gtk.Label(label="🖼 aucune image", xalign=0)
        h.pack_start(self.chat_img_label, True, True, 0)
        b_img = Gtk.Button(label="📎 Fichier")
        b_img.set_tooltip_text("Joindre : image (lue par le moteur Flash) ou texte/txt/md/code (inclus dans le message). PDF/Word : extraction à venir.")
        b_img.connect("clicked", lambda *_: self.ui_chat_image())
        h.pack_start(b_img, False, False, 0)
        self.b_chat_stop2 = Gtk.Button(label="⏹ Stop")
        self.b_chat_stop2.connect("clicked", lambda *_: self.ui_chat_stop())
        h.pack_start(self.b_chat_stop2, False, False, 0)
        self.b_chat_send = Gtk.Button(label="➤ Envoyer")
        self.b_chat_send.get_style_context().add_class("suggested-action")
        self.b_chat_send.connect("clicked", lambda *_: self.ui_chat_send())
        h.pack_start(self.b_chat_send, False, False, 0)
        cv.pack_start(h, False, False, 0)
        comp.add(cv)
        box.pack_start(comp, False, False, 0)

        # Sessions persistantes : restaure la courante au lancement
        self.sessions = load_sessions()
        if not self.sessions["sessions"]:
            self.sessions["sessions"] = [{"id": "s1", "title": "Conversation 1",
                                          "model": "", "updated": "", "messages": []}]
            self.sessions["current"] = "s1"
        self._sess_lock = False
        self.refresh_sess_combo()
        self.render_history()
        return box

    # ----- sessions -----
    def cur_sess(self):
        for s in self.sessions["sessions"]:
            if s["id"] == self.sessions["current"]:
                return s
        self.sessions["current"] = self.sessions["sessions"][0]["id"]
        return self.sessions["sessions"][0]

    def refresh_sess_combo(self):
        self._sess_lock = True
        self.sess_combo.remove_all()
        for i, s in enumerate(self.sessions["sessions"]):
            n = len([m for m in s["messages"] if m.get("role") == "user"])
            self.sess_combo.append_text(f"{s['title']} ({n} msg)")
            if s["id"] == self.sessions["current"]:
                self.sess_combo.set_active(i)
        self._sess_lock = False

    def render_history(self):
        for ch in self.chat_list.get_children():
            self.chat_list.remove(ch)
        s = self.cur_sess()
        self.chat_history = [dict(m) for m in s.get("messages", [])]
        for m in self.chat_history:
            self.chat_add_msg(m.get("role", "assistant"), msg_text(m), m.get("ts"))
        self.chat_add_msg  # noqa (garde la ref)

    def persist_current(self):
        try:
            s = self.cur_sess()
            s["messages"] = [dict(m) for m in self.chat_history]
            import datetime as _dt
            s["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
            if not s.get("title") or s["title"].startswith("Conversation"):
                for m in self.chat_history:
                    if m.get("role") == "user" and msg_text(m).strip():
                        s["title"] = msg_text(m).strip().splitlines()[0][:40]
                        break
            save_sessions(self.sessions)
            self.refresh_sess_combo()
        except Exception:
            pass

    def ui_sess_switch(self):
        if getattr(self, "_sess_lock", False):
            return
        i = self.sess_combo.get_active()
        if i is None or i < 0 or self.chat_busy:
            return
        self.persist_current()
        self.sessions["current"] = self.sessions["sessions"][i]["id"]
        save_sessions(self.sessions)
        self.render_history()

    def ui_sess_delete(self):
        if self.chat_busy:
            self.notify("Attends la fin de la réponse pour supprimer.")
            return
        if len(self.sessions["sessions"]) <= 1:
            self.notify("Dernière session : utilise 🧹 Nouvelle pour repartir à zéro.")
            return
        cur = self.cur_sess()
        dlg = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.OK_CANCEL,
                                text=f"Supprimer « {cur.get('title', '?')} » ?")
        ok = dlg.run() == Gtk.ResponseType.OK
        dlg.destroy()
        if not ok:
            return
        self.sessions["sessions"] = [s for s in self.sessions["sessions"] if s["id"] != cur["id"]]
        self.sessions["current"] = self.sessions["sessions"][0]["id"]
        save_sessions(self.sessions)
        self.refresh_sess_combo()
        self.render_history()
        self.log(f"Session supprimée : {cur.get('title', '?')}")

    def ui_chat_new(self):
        if self.chat_busy:
            self.notify("Attends la fin de la réponse pour changer.")
            return
        self.persist_current()
        import time as _t
        nid = f"s{int(_t.time())}"
        self.sessions["sessions"].append({"id": nid, "title": f"Conversation {len(self.sessions['sessions']) + 1}",
                                          "model": "", "updated": "", "messages": []})
        self.sessions["sessions"] = self.sessions["sessions"][-15:]
        self.sessions["current"] = nid
        save_sessions(self.sessions)
        self.refresh_sess_combo()
        self.render_history()

    def chat_add_msg(self, who, text="", ts=None, live=False):
        """Ajoute une bulle ; retourne le label pour ajouts incrementaux."""
        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        ctx = row.get_style_context()
        ctx.add_class("chat-row")
        ctx.add_class("chat-user" if who == "user" else "chat-assistant")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, margin=8)
        head = Gtk.Box(spacing=6)
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{'🧑 Toi' if who == 'user' else '🐦 Colibri v2.0'}</b>")
        head.pack_start(title, False, False, 0)
        when = Gtk.Label(xalign=0)
        if ts:
            when.set_markup(f"<small><span alpha='55%'>{ts}</span></small>")
        head.pack_start(when, False, False, 0)
        if live:
            self._pending_time = when
        v.pack_start(head, False, False, 0)
        body = Gtk.Label(label=text, xalign=0, selectable=True)
        body.set_line_wrap(True)
        body.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        v.pack_start(body, False, False, 0)
        row.add(v)
        self.chat_list.add(row)
        self.chat_list.show_all()
        GLib.idle_add(lambda: self._chat_scroll())
        return body

    @staticmethod
    def now_hm():
        return time.strftime("%H:%M")

    def _chat_scroll(self):
        adj = self.chat_sw.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    def ui_chat_stop(self):
        if self.chat_busy:
            self.chat_abort = True
            self.notify("Arrêt demandé...")
        else:
            self.notify("Rien en cours.")

    # extensions lues comme images par le moteur (tour vision)
    IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    # extensions incluses comme texte (stdlib, sans dependance)
    TXT_EXTS = {".txt", ".md", ".markdown", ".json", ".csv", ".tsv", ".log",
                ".py", ".js", ".ts", ".tsx", ".c", ".h", ".cc", ".cpp", ".rs",
                ".nix", ".sh", ".yaml", ".yml", ".toml", ".xml", ".html", ".css"}
    TXT_MAX_CHARS = 30000

    def ui_chat_image(self):
        dlg = Gtk.FileChooserDialog(title="Joindre un fichier", parent=self,
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Choisir", Gtk.ResponseType.OK)
        f = Gtk.FileFilter()
        f.set_name("Images + texte")
        for pat in ["*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp",
                    "*.txt", "*.md", "*.json", "*.csv", "*.log",
                    "*.py", "*.js", "*.ts", "*.c", ".h", "*.rs",
                    "*.nix", "*.sh", "*.yaml", "*.toml",
                    "*.pdf", "*.docx", "*.odt"]:
            f.add_pattern(pat)
            f.add_pattern(pat.upper())
        dlg.add_filter(f)
        fa = Gtk.FileFilter()
        fa.set_name("Tous fichiers")
        fa.add_pattern("*")
        dlg.add_filter(fa)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return
        path = dlg.get_filename()
        dlg.destroy()
        ext = os.path.splitext(path)[1].lower()
        if ext in self.IMG_EXTS:
            self.chat_image = path
            self.chat_img_label.set_text("🖼 " + os.path.basename(path))
            self.log(f"Image jointe : {path}")
        elif ext in self.TXT_EXTS:
            try:
                with open(path, errors="replace") as fh:
                    txt = fh.read(self.TXT_MAX_CHARS + 1)
                if len(txt) > self.TXT_MAX_CHARS:
                    txt = txt[:self.TXT_MAX_CHARS] + "\n\n[...tronqué...]"
                block = f"\n\n[Fichier joint : {os.path.basename(path)}]\n```\n{txt}\n```\n"
                cur = self.chat_entry.get_text()
                self.chat_entry.set_text((cur + " " + block).strip()[:60000])
                self.log(f"Texte inclus depuis : {path} ({len(txt)} car.)")
            except OSError as e:
                self.log(f"Lecture impossible : {e}")
        elif ext in (".pdf", ".docx", ".odt"):
            self.log(f"{path} : extraction {ext} pas encore installée "
                     "(ni pdftotext, ni pandoc, ni lib python). "
                     "Copie le texte à la main pour l'instant.")
            self.notify("PDF/Word : extraction non installée pour l'instant.")
        else:
            self.log(f"Extension {ext or '?'} non gérée : envoie le contenu en texte.")

    def serve_base(self):
        return f"http://127.0.0.1:{self.e_port.get_text().strip()}"

    def serve_up(self):
        import urllib.request
        try:
            with urllib.request.urlopen(self.serve_base() + "/v1/models", timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    def ui_chat_send(self):
        import urllib.request
        text = self.chat_entry.get_text().strip()
        if not text or self.chat_busy:
            return
        m, d = self.run_params()
        if not m:
            return
        self.chat_entry.set_text("")
        user_content = text
        img = self.chat_image
        self.chat_image = None
        self.chat_img_label.set_text("🖼 aucune image")
        self.chat_add_msg("user", (f"🖼 {os.path.basename(img)}\n" if img else "") + text,
                              self.now_hm())
        msgs = list(self.chat_history)
        sent_ts = self.now_hm()
        if img:
            api_user = {"role": "user", "ts": sent_ts, "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": img}}]}
        else:
            api_user = {"role": "user", "ts": sent_ts, "content": text}
        msgs.append(api_user)
        body_label = self.chat_add_msg("assistant", "…", live=True)
        self.chat_busy = True
        self.chat_abort = False
        think = self.c_think.get_active_text()
        payload = {"model": "qwen3.8-flash-next-colibri", "messages": msgs,
                   "max_tokens": int(self.conf.get("ngen", 128) or 128),
                   "stream": True}
        if think == "no-think":
            payload["enable_thinking"] = False
        else:
            payload["reasoning_effort"] = think
        base = self.serve_base()

        def work():
            import json as _json
            # demarre le serve si besoin (mêmes réglages que Lancer)
            if not self.serve_up():
                GLib.idle_add(body_label.set_text, "Démarrage du serveur…")
                cmd = [self.coli(), "serve", "--model", d, "--ctx", self.conf["ctx"],
                       "--cap", self.conf["cap"], "--port", self.conf["port"]]
                GLib.idle_add(self.log, "$ " + " ".join(cmd))
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as e:
                    GLib.idle_add(body_label.set_text, f"Erreur serve : {e}")
                    GLib.idle_add(self._chat_done)
                    return
                for _ in range(150):
                    if self.serve_up():
                        break
                    time.sleep(2)
                else:
                    GLib.idle_add(body_label.set_text, "Serveur injoignable après 5 min.")
                    GLib.idle_add(self._chat_done)
                    return
            data = _json.dumps(payload).encode()
            req = urllib.request.Request(base + "/v1/chat/completions", data=data,
                                         headers={"Content-Type": "application/json"})
            buf, full = [""], [""]
            try:
                with urllib.request.urlopen(req, timeout=1200) as r:
                    for raw in r:
                        if self.chat_abort:
                            break
                        line = raw.decode(errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        js = line[5:].strip()
                        if js == "[DONE]":
                            break
                        try:
                            ch = _json.loads(js)["choices"][0].get("delta", {})
                        except (ValueError, KeyError, IndexError):
                            continue
                        t = ch.get("content") or ch.get("reasoning_content") or ""
                        if t:
                            buf[0] += t
                            full[0] += t
                    if buf[0]:
                        chunk = buf[0]
                        buf[0] = ""
                        GLib.idle_add(self._chat_append, body_label, chunk)
            except Exception as e:
                GLib.idle_add(body_label.set_text, f"Erreur : {e}")
                GLib.idle_add(self._chat_done)
                return
            if buf[0]:
                GLib.idle_add(self._chat_append, body_label, buf[0])
            GLib.idle_add(self._chat_finish, full[0], api_user)

        threading.Thread(target=work, daemon=True).start()

    def _chat_append(self, label, chunk):
        try:
            label.set_text(label.get_text() + chunk)
            self._chat_scroll()
        except Exception:
            pass

    def _chat_finish(self, answer, api_user_msg):
        ts = self.now_hm()
        if getattr(self, "_pending_time", None) is not None:
            try:
                self._pending_time.set_markup(f"<small><span alpha='55%'>{ts}</span></small>")
            except Exception:
                pass
            self._pending_time = None
        if answer.strip():
            self.chat_history.append(api_user_msg)
            self.chat_history.append({"role": "assistant", "ts": ts, "content": answer})
            self.chat_history = self.chat_history[-20:]
            try:
                cur = self.cur_sess()
                if not cur.get("model"):
                    m = self.selected_model()
                    cur["model"] = m["id"] if m else ""
            except Exception:
                pass
            self.persist_current()
        self._chat_done()

    def _chat_done(self):
        self.chat_busy = False
        self.chat_abort = False

    # ---------- onglet Système ----------
    def page_sys(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=12)
        h = Gtk.Box(spacing=6)
        b = Gtk.Button(label="↻ Actualiser ressources")
        b.connect("clicked", lambda *_: self.refresh_sys())
        h.pack_start(b, False, False, 0)
        box.pack_start(h, False, False, 0)
        self.sys_view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD)
        sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        sw.set_min_content_height(300)
        sw.add(self.sys_view)
        frame = Gtk.Frame(label="RAM / Disque / GPU / Binaire")
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame.add(sw)
        box.pack_start(frame, True, True, 0)
        GLib.timeout_add(600, lambda: (self.refresh_sys(), False)[1])
        return box

    def refresh_sys(self):
        lines = []
        ok, out = run_cmd(["free", "-g"])
        lines.append("== RAM ==\n" + (out.splitlines()[1] if ok and len(out.splitlines()) > 1 else out))
        try:
            st = os.statvfs(self.conf["models_dir"])
            free_gb = st.f_bavail * st.f_frsize / 1e9
            lines.append(f"\n== Disque modèles ({self.conf['models_dir']}) ==\n{free_gb:.0f} Go libres")
        except OSError as e:
            lines.append(f"\n== Disque ==\n{e}")
        ok, out = run_cmd(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                           "--format=csv,noheader"], timeout=10)
        lines.append("\n== GPU ==\n" + (out if ok else "nvidia-smi indisponible"))
        ok, out = run_cmd([self.coli(), "--version"], timeout=10)
        lines.append("\n== coli ==\n" + (out.splitlines()[0] if ok and out else "coli introuvable"))
        try:
            self.sys_view.get_buffer().set_text("\n".join(lines))
        except AttributeError:
            pass


def main():
    w = Launcher()

    def on_destroy(*_):
        try:
            w.persist_current()
        except Exception:
            pass
        Gtk.main_quit()

    w.connect("destroy", on_destroy)
    w.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
