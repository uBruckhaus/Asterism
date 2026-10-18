"""Installing and removing an agent or a local LLM from its recipe (install_recipes), as a mixin of
ai_popup.AgentsMap: from its card on the Add-ons page and from its right-click menu on the map.

The dialog always shows the exact command (with Copy). When the app may start it, it runs in a
terminal window the user watches (sudo asks for the password there; the app never sees it), and the
app checks every few seconds whether it is in (or out) now. The app's own installers keep their
install page. Removing names the data folders that stay, with their size: they are never touched.
"""

from __future__ import annotations

import threading
import time
import types
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

import agents
import disk_usage
import harnesses
import install_ctl
import install_recipes
import inventory
import providers
from i18n import _

WATCH_EVERY = 3            # seconds
WATCH_FOR = 20 * 60        # give up after this


class InstallDialog:
    def install_subject(self, kind: str, key: str):
        """(name, installed, source, ways, data) of an agent or a local LLM, or None."""
        if kind == "agent":
            h = harnesses.get(key)
            agent = next((a for a in self.agent_list if a.command == key), None)
            if h is None:
                return None
            return (agent.name if agent else h.full_name or h.name, bool(agent and agent.installed),
                    agent.source if agent else "", h.install, h.data)
        p = providers.get(key)
        rt = next((r for r in self.inventory.runtimes if r.key == key), None)
        if p is None or p.kind != "local":
            return None
        inst = install_ctl.INSTALLERS.get(key)
        own = inst is not None and inst.installed_folder() is not None
        installed = bool(rt and rt.installed)
        return p.name, installed, "own" if own else ("package" if installed else ""), p.install, p.data

    def offer_install(self, kind: str, key: str, action: str = "install"):
        subject = self.install_subject(kind, key)
        if subject is None:
            return
        name, installed, source, ways, data = subject
        step = install_recipes.choose(ways, action, source)
        if step is None:
            self.toast(_("Asterism knows no way to change {0} here.").format(name), 6)
            return
        if step.installer:
            target = types.SimpleNamespace(key=key, name=name, installed=installed)
            self.open_install(target, "uninstall" if action == "uninstall" else "install")
            return
        remove = action == "uninstall"
        if step.kind == "manual":
            body = _("Get {0} from its web page.").format(name) + (f"\n\n{step.note}" if step.note else "")
        elif step.run is None:
            body = _("Asterism cannot run this itself. Run it in a terminal:")
        elif step.sudo:
            body = _("Asterism runs this in a terminal window. It asks for your password there; Asterism never "
                     "sees it.")
        else:
            body = _("Asterism runs this in a terminal window, so you see every line.")
        dialog = Adw.AlertDialog(heading=(_("Remove {0}?") if remove else _("Install {0}?")).format(name), body=body)
        extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        text = "\n".join(step.commands) or step.url
        if text:
            view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8, left_margin=8)
            view.get_buffer().set_text(text)
            view.add_css_class("card")
            extra.append(view)
        if remove and data:
            stays = Gtk.Label(xalign=0, wrap=True, max_width_chars=1)
            stays.add_css_class("am-agent-detail")
            stays.set_label(_("What stays: {0}").format(", ".join(data)))
            extra.append(stays)
            self.measure_stays(stays, data)
        dialog.set_extra_child(extra)
        dialog.add_response("cancel", _("Cancel"))
        if text:
            dialog.add_response("copy", _("Copy command") if step.commands else _("Copy address"))
        if step.kind == "manual" and step.url:
            dialog.add_response("web", _("Open web page"))
        if step.run is not None:
            dialog.add_response("run", _("Remove in a terminal") if remove else _("Install in a terminal"))
            dialog.set_response_appearance("run", Adw.ResponseAppearance.DESTRUCTIVE if remove
                                           else Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("run")

        def answered(_d, response):
            if response == "copy":
                Gdk.Display.get_default().get_clipboard().set(text)
                self.toast(_("Copied."), 3)
            elif response == "web":
                try:
                    Gio.AppInfo.launch_default_for_uri(step.url, None)
                except GLib.Error:
                    pass
            elif response == "run":
                if self.run_in_window(step, kind, key, name, remove):
                    self.watch_install(kind, key, name, not remove)
                elif install_recipes.run(step):
                    self.toast(_("{0}: running in a terminal. Asterism looks again when it is done.").format(name), 6)
                    self.watch_install(kind, key, name, not remove)
                else:
                    Gdk.Display.get_default().get_clipboard().set(text)
                    self.toast(_("No terminal could be opened; the command is copied."), 6)
        dialog.connect("response", answered)
        dialog.present(self.window)

    @staticmethod
    def installs_in_window() -> bool:
        """Add-ons page › Run installs in the window's terminal (on unless switched off)."""
        import ai_core
        return ai_core.load_settings().get("installs_in_window") is not False

    def run_in_window(self, step, kind: str, key: str, name: str, remove: bool) -> bool:
        """The step's commands in a terminal tab of the window (VTE), when that is on and VTE is
        there; sudo asks for the password in it. False: use a terminal window instead."""
        import shlex
        import terminal_pane
        if not self.installs_in_window() or terminal_pane.vte() is None or not step.run:
            return False
        done = _("Done. You can close this tab (Back).")
        script = " && ".join(shlex.join(c) for c in step.run) + f"; echo; echo {shlex.quote(done)}"
        title = (_("Remove {0}") if remove else _("Install {0}")).format(name)
        tab = f"install:{kind}:{key}"
        old = self.sessions.pop(tab, None)
        if old is not None:
            if old.running:
                self.show_terminal(tab)
                return True
            self.right_stack.remove(old)
        subject = types.SimpleNamespace(name=title, command=tab)
        # Back goes where it was started: the Add-ons page (with the card, now up to date), else the map.
        from_addons = self.page_name() == "addons"

        def back():
            if from_addons and hasattr(self, "open_addons"):
                # Not open_addons(): its Back must still lead where it led before, not to this tab.
                self.addons_stack.set_visible_child_name("list")
                self.show_page("addons")
                self.addons_select = key
                self.refresh_addons()
            else:
                self.show_view("main", save=False)
        pane = terminal_pane.TerminalPane(subject, str(Path.home()), self.theme.colors, on_back=back,
                                          on_state=lambda _p: GLib.idle_add(self.terminal_changed),
                                          argv=["bash", "-c", script])
        self.sessions[tab] = pane
        self.right_stack.add_named(pane, f"term:{tab}")
        self.show_terminal(tab)
        return True

    def measure_stays(self, label, data):
        """The data folders' sizes, measured in the background (bounded like Help › Disk space)."""
        def work():
            seen, out = set(), []
            stop = time.monotonic() + 8
            for path in data:
                place = disk_usage.Place("data", Path.home() / path[2:])
                disk_usage._walk(place, seen, stop)
                if not place.missing:
                    out.append(f"{path} ({self.size_label(place.size)})")
            return out

        def done(found):
            if found and label.get_parent() is not None:
                label.set_label(_("What stays: {0}").format(", ".join(found)))
            return False
        threading.Thread(target=lambda: GLib.idle_add(done, work()), daemon=True).start()

    @staticmethod
    def size_label(n: int) -> str:
        for size, unit in ((1e12, "TB"), (1e9, "GB"), (1e6, "MB")):
            if n >= size:
                return f"{n / size:.1f} {unit}"
        return f"{max(0, n) // 1000} kB"

    def is_installed_now(self, kind: str, key: str) -> bool:
        if kind == "agent":
            return agents.detect(key)[0]
        p = providers.get(key)
        try:
            return bool(p and p.detect and p.detect(inventory.own_processes()).installed)
        except Exception:
            return False

    def watch_install(self, kind: str, key: str, name: str, want: bool):
        """Look again every few seconds until it is in (want=True) or out; then refresh everything."""
        until = time.monotonic() + WATCH_FOR

        def tick():
            if self.is_installed_now(kind, key) == want:
                self.collect()
                self.refresh_overview()
                self.refresh_map()
                if hasattr(self, "refresh_addons") and self.page_name() == "addons":
                    self.refresh_addons()
                self.toast((_("{0} is installed.") if want else _("{0} is removed.")).format(name), 5)
                return False
            return time.monotonic() < until

        GLib.timeout_add_seconds(WATCH_EVERY, tick)
