"""The add-on API (Asterism only; the AI Agents Map plugin has no add-ons).

An add-on's addon.py defines register(api); `api` is an AddonAPI. Everything an add-on may do goes
through it, so the app's internals can change without breaking add-ons. API_VERSION changes only on
a breaking change; additions keep it.

Hook points (the only places an add-on appears):
    api.add_session_titles(command, reader)       reader() -> {session id: title}   (TITLES)
    api.add_details_section(builder, privacy)     builder(ui, box, harness, sessions, since)
    api.add_help_card(builder)                    builder(ui, box)
    api.add_settings_group(builder)               builder(ui, box)
    api.add_harness(api.Harness(...))             a new agent: cards, map, details     ("agent")
    api.add_provider(api.Provider(...))           a new local LLM or online provider    ("provider")

Agents and providers need the capability in quotes declared in addon.json ("capabilities"), and
one that brings an installer also "installer". A built-in id cannot be replaced, and an add-on's
agent cannot bring an updater of its own (agent_updates only runs built-in updaters).

An add-on may never do more than the privacy level its addon.json declares (edition.NUMBERS,
TITLES or SUMMARY); registering a hook above it raises AddonError. Callbacks run inside try/except:
an add-on that fails is reported in Settings, the page goes on without it.
"""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field

import edition as _edition
import harnesses

API_VERSION = 1
PRIVACY = {"numbers": _edition.NUMBERS, "titles": _edition.TITLES, "summary": _edition.SUMMARY}
CAPABILITIES = ("agent", "provider", "installer")


class AddonError(Exception):
    pass


@dataclass
class Hooks:
    titles: dict = field(default_factory=dict)        # command -> [(addon id, reader)]
    details: list = field(default_factory=list)       # [(addon id, builder, privacy)]
    help: list = field(default_factory=list)          # [(addon id, builder)]
    settings: list = field(default_factory=list)      # [(addon id, builder)]
    privacy: dict = field(default_factory=dict)       # addon id -> level of a loaded add-on
    errors: dict = field(default_factory=dict)        # addon id -> last error text

    def clear(self):
        self.__init__()


HOOKS = Hooks()


def loaded_privacy() -> int:
    """The highest privacy level of the add-ons loaded now (0 without any)."""
    return max(HOOKS.privacy.values(), default=0)


def failed(addon_id: str, error: BaseException | str, hooks: Hooks | None = None):
    text = error if isinstance(error, str) else "".join(traceback.format_exception_only(type(error), error)).strip()
    (hooks or HOOKS).errors[addon_id] = text[:500]


def call(addon_id: str, fn, *args):
    """Run an add-on's callback; a failure is noted, never raised."""
    try:
        return fn(*args)
    except Exception as error:          # an add-on's bug must not break the page
        failed(addon_id, error)
        return None


class AddonAPI:
    """What register(api) gets: one per add-on, knowing its id, privacy and translations."""

    version = API_VERSION
    NUMBERS, TITLES, SUMMARY = _edition.NUMBERS, _edition.TITLES, _edition.SUMMARY

    def __init__(self, addon_id: str, privacy: int, strings: dict | None = None, hooks: Hooks = HOOKS,
                 capabilities=()):
        self.addon_id = addon_id
        self.privacy = privacy
        self.capabilities = frozenset(capabilities)
        self._strings = strings or {}       # language -> {English text: translation}
        self._hooks = hooks

    # --- what the add-on may read ---
    @property
    def edition(self) -> int:
        return _edition.maximum()

    @property
    def harnesses(self):
        return harnesses

    def session_titles(self, command: str) -> dict:
        """Titles other add-ons provide for a harness (merged)."""
        found = {}
        for addon_id, reader in self._hooks.titles.get(command, []):
            result = call(addon_id, reader)
            if isinstance(result, dict):
                found.update({str(k): str(v) for k, v in result.items()})
        return found

    def tr(self, text: str) -> str:
        """The add-on's own translation of `text` in the app's language (English when missing)."""
        import i18n
        found = self._strings.get(i18n.current(), {}).get(text, text)
        return found if isinstance(found, str) else text

    def trn(self, one: str, other: str, n: int) -> str:
        """Plural, as the app's ngettext: the forms under "\\x04" + `one` in the add-on's tables."""
        import i18n
        lang = i18n.current()
        return i18n.pick_plural(lang, self._strings.get(lang, {}).get(i18n.PLURAL_PREFIX + one), n, one, other)

    # --- helpers an add-on may use (bounded, owner-only, read-only where it reads) ---
    @staticmethod
    def run_bounded(argv: list, max_bytes: int = 64 * 1024, timeout: float = 5.0, stdin: bytes | None = None,
                    cwd: str | None = None) -> tuple:
        """(output bytes, ok): no shell, output capped, one deadline (ai_core.read_bounded_output)."""
        import ai_core
        return ai_core.read_bounded_output(list(argv), max_bytes=max_bytes, timeout=timeout, stdin=stdin, cwd=cwd)

    @staticmethod
    def atomic_write(path, text: str) -> None:
        """Write a file owner-only in one step (ai_core.atomic_write)."""
        import ai_core
        ai_core.atomic_write(path, text)

    @staticmethod
    def open_readonly(path):
        """A harness's SQLite database read-only (never created or changed), or None."""
        from pathlib import Path
        return harnesses.connect(Path(path))

    def cache_dir(self):
        """The add-on's own cache folder (owner-only), created on first use."""
        import os
        from pathlib import Path
        folder = Path.home() / ".cache/asterism/addons" / self.addon_id
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(folder, 0o700)
        return folder

    @property
    def claude_projects(self):
        """Where Claude Code keeps its session files (~/.claude/projects, or CLAUDE_CONFIG_DIR's)."""
        import claude_sessions
        return claude_sessions.ROOT

    # --- hook points ---
    def _allow(self, level: int, what: str):
        if level > self.privacy:
            raise AddonError(f"{what} needs a higher privacy level than {self.addon_id} declares")

    def add_session_titles(self, command: str, reader):
        self._allow(_edition.TITLES, "add_session_titles")
        self._hooks.titles.setdefault(command, []).append((self.addon_id, reader))

    def add_details_section(self, builder, privacy: int = _edition.NUMBERS):
        self._allow(privacy, "add_details_section")
        self._hooks.details.append((self.addon_id, builder, privacy))

    def add_help_card(self, builder):
        self._hooks.help.append((self.addon_id, builder))

    def add_settings_group(self, builder):
        self._hooks.settings.append((self.addon_id, builder))

    # --- new agents and providers ---
    from harnesses import Harness, LocalLlm, Mcp, Sessions, Skills   # noqa: E402  (classes for add-ons)
    from providers import Provider                                 # noqa: E402

    @staticmethod
    def ref(module: str, name: str):
        """harnesses.ref: a function of another module, imported when first called."""
        return harnesses.ref(module, name)

    @property
    def Runtime(self):
        """inventory.Runtime: what a local provider's detect(processes) returns."""
        import inventory
        return inventory.Runtime

    def _need(self, capability: str, what: str):
        if capability not in self.capabilities:
            raise AddonError(f"{what} needs \"{capability}\" in {self.addon_id}'s capabilities")

    def add_harness(self, harness):
        self._need("agent", "add_harness")
        if harness.installer is not None:
            self._need("installer", "an agent with an installer")
        harnesses.add(harness, self.addon_id)

    def add_provider(self, provider):
        self._need("provider", "add_provider")
        if provider.installer is not None:
            self._need("installer", "a provider with an installer")
        import providers
        providers.add(provider, self.addon_id)


class UI:
    """The few widgets and helpers add-ons build with (a stable face over the app)."""

    def __init__(self, app, addon_id: str = ""):
        self._app = app
        self.addon_id = addon_id

    def heading(self, box, text: str):
        self._app.settings_heading(box, text)

    def boxed_list(self):
        return self._app.boxed_list()

    @staticmethod
    def box(spacing: int = 8):
        """A vertical box to put widgets in (e.g. a section filled once its data is read)."""
        from gi.repository import Gtk
        return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)

    def plain_row(self, title: str, subtitle: str = ""):
        return self._app.plain_row(title, subtitle)

    def expander_row(self, title: str, subtitle: str = ""):
        from gi.repository import Adw
        return Adw.ExpanderRow(title=title, subtitle=subtitle, use_markup=False)

    def note(self, box, text: str):
        self._app.note(box, text)

    def label(self, text: str = "", selectable: bool = True, card: bool = False):
        """Plain text (never markup); card=True: in a framed box, as a written answer."""
        from gi.repository import Gtk
        label = Gtk.Label(label=text, xalign=0, wrap=True, selectable=selectable)
        if card:
            label.add_css_class("card")
            label.add_css_class("am-summary")
        return label

    def button(self, label: str, on_click, tooltip: str = ""):
        from gi.repository import Gtk
        button = Gtk.Button(label=label, halign=Gtk.Align.START)
        if tooltip:
            button.set_tooltip_text(tooltip)
        button.connect("clicked", lambda *_a: call(self.addon_id, on_click))
        return button

    def confirm(self, heading: str, body: str, preview: str, confirm_label: str, on_confirm):
        """A dialog that shows `preview` (exactly what will happen or be sent); on_confirm only on OK."""
        from gi.repository import Adw, Gtk
        dialog = Adw.AlertDialog(heading=heading, body=body)
        view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(preview)
        scroller = Gtk.ScrolledWindow(min_content_height=240, max_content_height=420, propagate_natural_height=True)
        scroller.set_child(view)
        dialog.set_extra_child(scroller)
        import i18n
        dialog.add_response("cancel", i18n._("Cancel"))
        dialog.add_response("ok", confirm_label)
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.connect("response", lambda _d, response: response == "ok" and call(self.addon_id, on_confirm))
        dialog.present(self._app.window)

    def run_in_background(self, work, done=None):
        """work() on a thread; done(result) back on the UI thread (both guarded)."""
        from gi.repository import GLib

        def thread():
            result = call(self.addon_id, work)
            if done is not None:
                GLib.idle_add(lambda: (call(self.addon_id, done, result), False)[1])
        threading.Thread(target=thread, daemon=True).start()

    def toast(self, text: str, seconds: int = 4):
        self._app.toast(text, seconds)

    def duration_text(self, seconds: float) -> str:
        return self._app.duration_text(seconds)

    @staticmethod
    def short_number(n: int) -> str:
        for size, unit in ((10 ** 9, "B"), (10 ** 6, "M"), (10 ** 3, "k")):
            if n >= size:
                return f"{n / size:.1f}{unit}".replace(".0", "")
        return str(n)

    @staticmethod
    def tilde(path: str) -> str:
        import inventory
        return inventory.tilde(path)
