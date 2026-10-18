"""Asterism: the Add-ons page (a mixin of ai_popup.AgentsMap; not in the AI Agents Map plugin).

One place for everything the app understands: the agents and providers built in, the add-ons
installed (on, off, refused), the ones in the signed catalog, and the ones suggested because their
harness is on this PC. Cards with search and filters; a details view per add-on with what it reads,
sends and may do; install, switch on/off, update, remove, install from a file. Every change goes
through addon_store (signature and hashes first) and reload_addons (no restart).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

import addon_api
import addon_store
import addons
import ai_core
import desktop
import harnesses
import install_recipes
import providers
from i18n import _

KIND_ICONS = {"agent": "system-users-symbolic", "provider": "network-server-symbolic",
              "feature": "application-x-addon-symbolic"}
FILTERS = ("all", "agent", "provider", "feature", "installed", "updates")


@dataclass
class Item:
    id: str
    name: str
    kind: str                         # agent | provider | feature
    state: str                        # builtin | on | off | failed | available | suggested
    summary: str = ""
    description: str = ""
    version: str = ""
    icon: str = ""                    # icon name, or a glyph with glyph_font
    glyph: str = ""
    glyph_font: str = ""
    privacy: int = 1
    capabilities: list = field(default_factory=list)
    reads: list = field(default_factory=list)
    sends: list = field(default_factory=list)
    reason: str = ""
    entry: addon_store.Entry | None = None
    addon: addons.Addon | None = None
    update: bool = False
    installed: bool | None = None     # built-in agents and local LLMs: is the program itself here
    target: str = ""                  # "agent" | "runtime": what install_dialog installs or removes
    homepage: str = ""                # the web page of the agent, provider or add-on
    key: str = ""                     # the agent command or provider key install_dialog gets (else id)
    here: bool = False                # an add-on (off) whose program is on this PC: suggested
    words: str = ""                   # what search looks through


def privacy_name(level: int) -> str:
    return {1: _("Numbers only"), 2: _("Session titles"), 3: _("Titles and a summary by Claude")}.get(level, "")


def capability_text(capability: str) -> str:
    return {"agent": _("Adds an agent to the map and the cards"),
            "provider": _("Adds an LLM provider to the map"),
            "installer": _("Can install a program (from a download checked against its release's SHA-256)")
            }.get(capability, capability)


def harness_summary(h) -> str:
    parts = [part for part, has in ((_("sessions"), h.sessions), (_("security"), h.security),
                                    (_("MCP servers"), h.mcp), (_("skills"), h.skills),
                                    (_("local LLMs"), h.local_llm), (_("updates"), h.self_update))
             if has]
    return " · ".join(parts) if parts else _("Shown on the map")


def build_items(installed: list, entries: list, agent_list=(), runtimes=()) -> list:
    """Built-ins, installed add-ons and catalog entries as one list of cards."""
    agent_on = {a.command: a.installed for a in agent_list}
    runtime_on = {r.key: r.installed for r in runtimes}
    items = []
    by_id = {e.id: e for e in entries}
    for addon in installed:
        entry = by_id.pop(addon.id, None)
        if addon.state in ("refused", "failed"):
            state = "failed"
        else:
            state = "on" if addon.state == "loaded" else "off"
        kind = addon.kind if addon.kind != "feature" else entry.kind if entry else "feature"
        item = Item(addon.id, addon.name or addon.id, kind, state,
                    (entry.summary if entry else "") or addon.summary,
                    (entry.description if entry else "") or addon.description, addon.version,
                    (entry.icon if entry else "") or addon.icon or KIND_ICONS[kind], privacy=addon.privacy or 1,
                    capabilities=list(addon.capabilities), reads=list(addon.reads), sends=list(addon.sends),
                    reason=addon.reason, entry=entry, addon=addon,
                    update=bool(entry and addon.version and addon_store.newer(entry.version, addon.version)),
                    homepage=(entry.homepage if entry else "") or addon.homepage)
        if entry and item.kind == "feature" and "agent" in addon.capabilities:
            item.kind = "agent"
        if addon.kind in ("agent", "provider") and len(addon.provides) == 1:
            # An adapter: the program it brings, installed and removed from its card once it is on.
            key = item.key = addon.provides[0]
            if addon.kind == "agent" or addon.commands or "installer" in addon.capabilities:     # a program
                known = agent_on if addon.kind == "agent" else runtime_on
                item.installed = known[key] if key in known else addon_store.present(addon)
                item.target = ("agent" if addon.kind == "agent" else "runtime") if state == "on" else ""
                item.here = state == "off" and bool(item.installed)
        items.append(item)
    for entry in by_id.values():
        items.append(Item(entry.id, entry.name, entry.kind, "suggested" if addon_store.present(entry) else "available",
                          entry.summary, entry.description, entry.version, entry.icon or KIND_ICONS[entry.kind],
                          privacy=entry.privacy, capabilities=list(entry.capabilities), reads=list(entry.reads),
                          sends=list(entry.sends), entry=entry, homepage=entry.homepage))
    for h in harnesses._built_in():
        items.append(Item(h.command, h.full_name or h.name, "agent", "builtin", harness_summary(h),
                          glyph=h.icon, glyph_font=h.icon_font, installed=agent_on.get(h.command, False),
                          target="agent" if h.install else "", homepage=h.homepage))
    for p in providers._built_in_local():
        items.append(Item(p.key, p.name, "provider", "builtin", _("Local LLM: found, installed, started and stopped "
                                                                  "here, its models on the map"),
                          icon=KIND_ICONS["provider"], installed=runtime_on.get(p.key, False),
                          target="runtime" if p.install else "", homepage=p.homepage))
    for p in providers._built_in_online():
        items.append(Item(p.key, p.name, "provider", "builtin", _("Online provider"), icon="network-workgroup-symbolic"))
    for item in items:
        item.words = " ".join([item.id, item.name, item.summary, item.description] + item.reads).lower()
    return items


def visible(item: Item, flt: str, query: str) -> bool:
    if query and query.lower() not in item.words:
        return False
    if flt == "installed":
        return item.state in ("on", "off", "failed")
    if flt == "updates":
        return item.update
    return flt == "all" or item.kind == flt


class AddonsPage:
    """The page; needs AgentsMap's helpers (page_scroller, boxed_list, plain_row, note, toast, …)."""

    def build_addons_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header = Gtk.Box(spacing=8)
        back = Gtk.Button()
        back.add_css_class("flat")
        back.add_css_class("am-header-btn")
        back.add_css_class("am-back-bordered")
        back_box = Gtk.Box(spacing=6)
        back_box.append(Gtk.Image.new_from_icon_name("go-previous-symbolic"))
        back_box.append(Gtk.Label(label=_("Back")))
        back_box.append(Gtk.Label(label="· ⌫"))
        back.set_child(back_box)
        back.set_tooltip_text(_("Back (Backspace, Esc)"))
        back.connect("clicked", lambda *_a: self.close_addons())
        header.append(back)
        title = Gtk.Label(label=_("Add-ons").upper(), xalign=0)
        title.add_css_class("am-section-title")
        header.append(title)
        self.addons_search = Gtk.SearchEntry(placeholder_text=_("Search add-ons, agents, providers…"),
                                             hexpand=True, max_width_chars=40, halign=Gtk.Align.END)
        self.addons_search.connect("search-changed", lambda *_a: self.fill_addons_list())
        header.append(self.addons_search)
        from_file = Gtk.Button(label=_("Install from file…"))
        from_file.add_css_class("am-small-btn")
        from_file.connect("clicked", lambda *_a: self.addon_from_file())
        header.append(from_file)
        page.append(header)
        rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        rule.add_css_class("am-settings-rule")
        page.append(rule)
        chips = Gtk.Box(spacing=6)
        self.addons_filter = "all"
        self.addons_chips = {}
        first = None
        labels = {"all": _("All"), "agent": _("Agents"), "provider": _("Providers"), "feature": _("Features"),
                  "installed": _("Installed"), "updates": _("Updates")}
        for key in FILTERS:
            chip = Gtk.ToggleButton(label=labels[key])
            chip.add_css_class("am-addon-chip")
            if first is None:
                first = chip
                chip.set_active(True)
            else:
                chip.set_group(first)
            chip.connect("toggled", lambda button, k=key: button.get_active() and self.set_addons_filter(k))
            chips.append(chip)
            self.addons_chips[key] = chip
        page.append(chips)
        drop = Gtk.Label(label=_("Drop an add-on (.zip from a folder, or a link from the web) anywhere on the "
                                 "window to add it."), xalign=0, wrap=True, hexpand=True)
        drop.add_css_class("am-agent-detail")
        line = Gtk.Box(spacing=8)
        line.append(drop)
        inside = Gtk.Label(label=_("Run installs in the window's terminal"))
        inside.add_css_class("am-agent-detail")
        line.append(inside)
        switch = Gtk.Switch(active=self.installs_in_window(), valign=Gtk.Align.CENTER)
        switch.set_tooltip_text(_("On: installs and removals run in a terminal tab here (sudo asks for your "
                                  "password in it). Off: in a terminal window of its own."))
        switch.connect("notify::active", lambda s, *_a: self.save_setting(installs_in_window=s.get_active()))
        line.append(switch)
        page.append(line)
        self.addons_status = Gtk.Label(xalign=0, wrap=True)
        self.addons_status.add_css_class("am-agent-detail")
        page.append(self.addons_status)
        self.addons_stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.addons_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_bottom=12)
        self.addons_stack.add_named(self.page_scroller(self.addons_list), "list")
        self.addons_detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_bottom=12)
        clamp = Adw.Clamp(maximum_size=820, child=self.addons_detail, unit=Adw.LengthUnit.PX)
        self.addons_stack.add_named(self.page_scroller(clamp), "detail")
        page.append(self.addons_stack)
        self.addons_items = []
        self.addons_entries = []
        return page

    # --- first start: "Set up Asterism" ---
    def adapter_addons(self) -> list:
        """The installed, valid add-ons that bring an agent or a provider."""
        return [a for a in self.addons if a.kind in ("agent", "provider") and a.state in ("verified", "loaded")]

    def setup_needed(self) -> bool:
        """Adapter add-ons are there and none is on: the map would be empty, so Asterism starts on
        the welcome page with the cards (also after Later, until something is switched on)."""
        adapters = self.adapter_addons()
        return bool(adapters) and not any(a.state == "loaded" for a in adapters)

    def installed_adapters(self, adapters: list) -> set:
        """Ids of the adapter add-ons whose program is really installed: every adapter is loaded for a
        moment and the app's own detection runs (a leftover settings folder or an empty shim does not
        count); then only the add-ons switched on are loaded again."""
        import agents
        import inventory
        enabled = ai_core.load_settings().get("addons_enabled", [])
        enabled = {e for e in enabled if isinstance(e, str)} if isinstance(enabled, list) else set()
        found = set()
        self.setup_glyphs = {}
        try:
            addons.load_all(enabled | {a.id for a in adapters})
            processes = inventory.own_processes()
            for addon in adapters:
                for key in addon.provides[:1]:
                    h = harnesses.get(key) if addon.kind == "agent" else None
                    if h is not None and h.icon:
                        # Omarchy's own font is only there on Omarchy: elsewhere the robot.
                        omarchy = h.icon_font == "omarchy"
                        self.setup_glyphs[addon.id] = (agents.ROBOT, "") if omarchy and desktop.NAME != "omarchy" \
                            else (h.icon, h.icon_font)
                    if addon.kind == "agent" and agents.detect(key)[0]:
                        found.add(addon.id)
                    p = providers.get(key) if addon.kind == "provider" and len(addon.provides) == 1 else None
                    if p is not None and p.detect is not None and p.detect(processes).installed:
                        found.add(addon.id)
        except Exception:
            found = {a.id for a in adapters if addon_store.present(a)}
        finally:
            self.load_addons()
        return found

    LOCAL_GLYPH, ONLINE_GLYPH, AGENT_GLYPH = "\U000F061A", "\U000F015F", "\U000f06a9"

    def build_setup_page(self) -> Gtk.Widget:
        """The welcome page of a new Asterism: the app's icon and a greeting, then the agents and
        local LLMs as cards with their icons; a click on a card ticks it, one button switches all on."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.setup_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_bottom=12)
        clamp = Adw.Clamp(maximum_size=900, child=self.setup_box, unit=Adw.LengthUnit.PX)
        page.append(self.page_scroller(clamp))
        page.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        buttons = Gtk.Box(spacing=8, margin_top=6, margin_bottom=6)
        self.setup_count = Gtk.Label(xalign=0, hexpand=True)
        self.setup_count.add_css_class("am-agent-detail")
        buttons.append(self.setup_count)
        later = Gtk.Button(label=_("Later"))
        later.set_tooltip_text(_("Start with an empty map; Settings › Add-ons › Set up brings this page back."))
        later.connect("clicked", lambda *_a: self.finish_setup(False))
        buttons.append(later)
        self.setup_ok = Gtk.Button()
        self.setup_ok.add_css_class("suggested-action")
        self.setup_ok.connect("clicked", lambda *_a: self.finish_setup(True))
        buttons.append(self.setup_ok)
        page.append(buttons)
        self.setup_checks = {}
        return page

    def setup_hero(self, found: int) -> Gtk.Widget:
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=18, margin_bottom=6)
        icon = Gtk.Image.new_from_icon_name(desktop.app_id())
        icon.set_pixel_size(72)
        hero.append(icon)
        title = Gtk.Label(label=_("Welcome to {0}").format(desktop.app_name()))
        title.add_css_class("am-setup-title")
        hero.append(title)
        text = _("Pick the AI agents and local LLMs you use. The ones found on this PC are already ticked: "
                 "one click on Switch on puts them on your map.") if found else \
            _("No agent or local LLM was found on this PC yet. Pick what you want to use: after Switch on, "
              "Asterism shows you how to install it.")
        line = Gtk.Label(label=text, wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=60)
        line.add_css_class("am-hint")
        hero.append(line)
        return hero

    def open_setup(self):
        """What Asterism found on this PC comes first, already ticked: one click puts it on the map.
        The rest can be ticked too and installed from its card afterwards."""
        box = self.setup_box
        while (child := box.get_first_child()) is not None:
            box.remove(child)
        self.setup_checks = {}
        adapters = self.adapter_addons()
        online = [a for a in adapters if a.kind == "provider" and len(a.provides) > 1]
        programs = [a for a in adapters if a not in online]
        installed = self.installed_adapters(programs)
        found = [a for a in programs if a.id in installed]
        before = [a for a in programs if a not in found and addon_store.present(a)]
        missing = [a for a in programs if a not in found and a not in before]
        on = {a.id for a in adapters if a.state == "loaded"}
        box.append(self.setup_hero(len(found)))
        # By kind, found ones first: agents, local LLMs, online providers. Found and online come ticked.
        state = {**{a.id: _("Installed") for a in found}, **{a.id: _("Used before") for a in before},
                 **{a.id: _("Not installed") for a in missing}, **{a.id: _("Online") for a in online}}
        ordered = found + before + missing
        for title, hint, group in (
                (_("AI agents"), _("The coding agents you work with in a terminal."),
                 [a for a in ordered if a.kind == "agent"]),
                (_("Local LLMs"), _("Programs that run language models on this PC."),
                 [a for a in ordered if a.kind == "provider"]),
                (_("Online providers"), _("The models your agents use on the web."), online)):
            if not group:
                continue
            self.settings_heading(box, title)
            self.note(box, hint)
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, column_spacing=10,
                               row_spacing=10, min_children_per_line=2, max_children_per_line=5)
            for addon in group:
                ticked = addon in found or addon in online or addon.id in on
                flow.append(self.setup_tile(addon, ticked, state[addon.id], addon in online,
                                            here=addon in found or addon in online))
            box.append(flow)
        if missing or before:
            self.note(box, _("Ticked but not installed: after Switch on, Asterism shows you how to install it."))
        self.setup_installed = installed
        self.update_setup_button()
        if self.page_name() not in ("setup", "settings", "help", "addons"):
            self.remember_page()
        self.show_page("setup")

    def setup_tile(self, addon, ticked: bool, state: str, online: bool, here: bool) -> Gtk.Widget:
        """One card: the agent's or provider's icon, its name and whether it is on this PC; the whole
        card is the tick (click, or Space on the focused card)."""
        tile = Gtk.ToggleButton(active=ticked)
        tile.add_css_class("am-setup-tile")
        if not here:
            tile.add_css_class("am-setup-absent")
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        top = Gtk.Box(spacing=8)
        glyph, font = getattr(self, "setup_glyphs", {}).get(addon.id) or \
            ((self.ONLINE_GLYPH if online else self.LOCAL_GLYPH) if addon.kind == "provider" else self.AGENT_GLYPH, "")
        icon = Gtk.Label(label=glyph, xalign=0, hexpand=True)
        icon.add_css_class("am-agent-icon")
        icon.add_css_class("am-setup-glyph")
        if font == "omarchy":
            icon.add_css_class("am-agent-icon-omarchy")
        top.append(icon)
        mark = Gtk.Label(label="✓", valign=Gtk.Align.START, visible=ticked)
        mark.add_css_class("am-setup-check")
        top.append(mark)
        body.append(top)
        name = Gtk.Label(label=addon.name, xalign=0, ellipsize=3, max_width_chars=1)
        name.add_css_class("am-addon-name")
        body.append(name)
        sub = Gtk.Label(label=state, xalign=0, ellipsize=3, max_width_chars=1)
        sub.add_css_class("am-agent-detail")
        if here and not online:
            sub.add_css_class("am-setup-here")
        body.append(sub)
        tile.set_child(body)
        tile.set_tooltip_text(addon.summary or addon.name)

        def toggled(button):
            mark.set_visible(button.get_active())
            self.update_setup_button()

        tile.connect("toggled", toggled)
        self.setup_checks[addon.id] = (tile, addon)
        return tile

    def update_setup_button(self):
        n = sum(1 for check, _addon in self.setup_checks.values() if check.get_active())
        self.setup_ok.set_label(_("Switch on {0}").format(n) if n else _("Switch on"))
        self.setup_ok.set_sensitive(n > 0)
        self.setup_count.set_label(_("Click a card to tick it or untick it."))

    def finish_setup(self, switch_on: bool):
        self.save_setting(setup_done=True)
        chosen = [addon for check, addon in self.setup_checks.values() if check.get_active()] if switch_on else []
        if not chosen:
            self.show_view("main", save=False)
            return
        for check, addon in self.setup_checks.values():
            addon_store.set_enabled(addon.id, check.get_active())
        self.reload_addons()
        absent = [a for a in chosen if (a.kind == "agent" or a.commands) and a.id not in self.setup_installed]
        self.toast(_("{0} add-ons are on.").format(len(chosen)), 4)
        if absent:
            # Ticked but not installed: their cards, with Install.
            self.addons_stack.set_visible_child_name("list")
            self.show_page("addons")
            self.addons_select = absent[0].id
            self.refresh_addons()
        else:
            self.show_view("main", save=False)

    # --- open, close, data ---
    def open_addons(self, select: str = ""):
        if self.page_name() not in ("settings", "help", "addons"):
            self.remember_page()
        self.addons_stack.set_visible_child_name("list")
        self.show_page("addons")
        self.addons_select = select
        self.refresh_addons()

    def close_addons(self):
        if self.addons_stack.get_visible_child_name() == "detail":
            self.addons_stack.set_visible_child_name("list")
            return
        self.back_to_last_page()

    def refresh_addons(self):
        """The cards from what is installed now; the catalog read in the background."""
        self.addons_items = build_items(self.addons, self.addons_entries, self.agent_list, self.inventory.runtimes)
        self.fill_addons_list()
        online = addon_store.online()
        self.addons_status.set_label(_("Looking for add-ons…") if online else
                                     _("Looking for add-ons online is off (Settings › Add-ons): only what is "
                                       "installed is shown."))

        def work():
            try:
                return addon_store.catalog(online)
            except Exception:
                return []

        def done(entries):
            self.addons_entries = entries
            self.addons_items = build_items(self.addons, entries, self.agent_list, self.inventory.runtimes)
            if online:
                self.addons_status.set_label(
                    _("Only add-ons signed by Uwe Bruckhaus are offered and loaded.") if entries else
                    _("The add-on catalog could not be read right now."))
            self.fill_addons_list()
            select = getattr(self, "addons_select", "")
            self.addons_select = ""
            item = next((i for i in self.addons_items if i.id == select), None)
            if item is not None:
                self.show_addon(item)
            return False

        threading.Thread(target=lambda: GLib.idle_add(done, work()), daemon=True).start()

    def set_addons_filter(self, key: str):
        self.addons_filter = key
        self.fill_addons_list()

    # --- the list ---
    def fill_addons_list(self):
        box = self.addons_list
        while (child := box.get_first_child()) is not None:
            box.remove(child)
        query = self.addons_search.get_text().strip()
        shown = [i for i in self.addons_items if visible(i, self.addons_filter, query)]
        updates = sum(1 for i in self.addons_items if i.update)
        self.addons_chips["updates"].set_label(_("Updates") + (f" {updates}" if updates else ""))
        sections = ((_("Suggested for this PC"), [i for i in shown if i.state == "suggested" or i.here]),
                    (_("Installed add-ons"), [i for i in shown if i.state in ("on", "off", "failed") and not i.here]),
                    (_("Available"), [i for i in shown if i.state == "available"]),
                    (_("Built into Asterism"), [i for i in shown if i.state == "builtin"]))
        for title, items in sections:
            if not items:
                continue
            heading = Gtk.Label(label=title, xalign=0)
            heading.add_css_class("heading")
            box.append(heading)
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, column_spacing=10,
                               row_spacing=10, min_children_per_line=1, max_children_per_line=4)
            for item in items:
                flow.append(self.addon_card(item))
            box.append(flow)
        if not shown:
            self.note(box, _("Nothing matches."))

    def addon_icon(self, item: Item, size: int = 24) -> Gtk.Widget:
        if item.glyph:
            label = Gtk.Label(label=item.glyph)
            label.add_css_class("am-agent-icon")
            if item.glyph_font == "omarchy":
                label.add_css_class("am-agent-icon-omarchy")
            return label
        image = Gtk.Image.new_from_icon_name(item.icon or KIND_ICONS.get(item.kind, KIND_ICONS["feature"]))
        image.set_pixel_size(size)
        return image

    def state_badge(self, item: Item) -> Gtk.Label:
        text, css = {"builtin": (_("Built in"), "am-addon-builtin"), "on": (_("On"), "am-addon-on"),
                     "off": (_("Off"), "am-addon-off"), "failed": (_("Not loaded"), "am-addon-failed"),
                     "available": (_("Available"), "am-addon-available"),
                     "suggested": (_("For this PC"), "am-addon-on")}[item.state]
        if item.update:
            text, css = _("Update"), "am-addon-on"
        badge = Gtk.Label(label=text, valign=Gtk.Align.CENTER)
        badge.add_css_class("am-addon-badge")
        badge.add_css_class(css)
        return badge

    def addon_card(self, item: Item) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("am-addon-card")
        if item.state == "suggested" or item.here:
            card.add_css_class("am-addon-suggested")
        if item.state == "failed":
            card.add_css_class("am-addon-refused")
        top = Gtk.Box(spacing=8)
        top.append(self.addon_icon(item))
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        name = Gtk.Label(label=item.name, xalign=0, ellipsize=3)
        name.add_css_class("am-addon-name")
        names.append(name)
        kind = {"agent": _("Agent"), "provider": _("Provider"), "feature": _("Feature")}[item.kind]
        if item.installed is not None and (item.target or item.key):
            kind += " · " + (_("installed") if item.installed else _("not installed"))
        sub = Gtk.Label(label=kind + (f" · {item.version}" if item.version else ""), xalign=0)
        sub.add_css_class("am-agent-detail")
        names.append(sub)
        top.append(names)
        if item.homepage:
            top.append(self.homepage_button(item))
        top.append(self.state_badge(item))
        card.append(top)
        summary = Gtk.Label(label=item.reason if item.state == "failed" else item.summary, xalign=0, wrap=True,
                            max_width_chars=1, lines=2, ellipsize=3)
        summary.add_css_class("am-agent-detail")
        card.append(summary)
        bottom = Gtk.Box(spacing=6)
        if item.state != "builtin":
            chip = Gtk.Label(label=privacy_name(item.privacy), xalign=0, hexpand=True)
            chip.add_css_class("am-addon-privacy")
            bottom.append(chip)
        else:
            bottom.append(Gtk.Box(hexpand=True))
        if item.target:
            bottom.append(self.program_buttons(item))
        else:
            action = self.addon_action(item)
            if action is not None:
                bottom.append(action)
        card.append(bottom)
        click = Gtk.GestureClick()
        click.connect("released", lambda *_a: self.show_addon(item))
        card.add_controller(click)
        card.set_tooltip_text(_("Click for details"))
        return card

    def homepage_button(self, item: Item, small: bool = True) -> Gtk.Button:
        """Opens the web page of the agent, provider or add-on in the browser."""
        if small:
            button = Gtk.Button(icon_name="web-browser-symbolic", valign=Gtk.Align.CENTER)
            button.add_css_class("flat")
            button.add_css_class("am-small-btn")
        else:
            button = Gtk.Button(label=_("Homepage"))
        button.set_tooltip_text(_("Open {0}").format(item.homepage))
        button.connect("clicked", lambda *_a: self.open_homepage(item.homepage))
        return button

    def open_homepage(self, url: str):
        if not addons.homepage(url):
            return
        try:
            Gio.AppInfo.launch_default_for_uri(url, None)
        except GLib.Error:
            self.toast(_("No browser could be opened."), 5)

    def addon_action(self, item: Item) -> Gtk.Widget | None:
        label, run = {"suggested": (_("Get add-on"), self.install_addon), "available": (_("Install"), self.install_addon),
                      "off": (_("Switch on"), self.switch_addon_on), "on": (_("Switch off"), self.switch_addon_off),
                      "failed": (_("Remove"), self.remove_addon)}.get(item.state, (None, None))
        if item.update:
            label, run = _("Update"), self.update_addon
        if label is None:
            return None
        button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
        button.add_css_class("am-small-btn")
        if item.state in ("suggested", "available") or item.update or item.state == "builtin":
            button.add_css_class("suggested-action")
        button.connect("clicked", lambda *_a: run(item))
        return button

    def program_buttons(self, item: Item, small: bool = True) -> Gtk.Widget:
        """Install and Uninstall for the program itself, always both; the one that does not apply now
        (or that has no way on this PC) is greyed out, with why in its tooltip."""
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        subject = self.install_subject(item.target, item.key or item.id)
        installed = bool(subject and subject[1])
        for action, label in (("install", _("Install")), ("uninstall", _("Uninstall"))):
            button = Gtk.Button(label=label if small else label + "…")
            if small:
                button.add_css_class("am-small-btn")
            step = install_recipes.choose(subject[3], action, subject[2]) if subject else None
            if action == "install" and installed:
                why = _("{0} is installed.").format(item.name)
            elif action == "uninstall" and not installed:
                why = _("{0} is not installed on this PC.").format(item.name)
            elif step is None:
                why = _("Asterism knows no way to change {0} here.").format(item.name)
            else:
                why = ""
            button.set_sensitive(not why)
            button.set_tooltip_text(why or (_("Shows the command first") if not step.installer else
                                            _("Opens the install page")))
            if not why and action == "install":
                button.add_css_class("suggested-action")
            button.connect("clicked", lambda *_a, a=action: self.offer_install(item.target, item.key or item.id, a))
            box.append(button)
        return box

    # --- details ---
    def show_addon(self, item: Item):
        box = self.addons_detail
        while (child := box.get_first_child()) is not None:
            box.remove(child)
        top = Gtk.Box(spacing=12)
        top.append(self.addon_icon(item, 48))
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        name = Gtk.Label(label=item.name, xalign=0)
        name.add_css_class("title-2")
        names.append(name)
        kind = {"agent": _("Agent"), "provider": _("Provider"), "feature": _("Feature")}[item.kind]
        line = Gtk.Label(label=kind + (f" · {item.version}" if item.version else ""), xalign=0)
        line.add_css_class("am-agent-detail")
        names.append(line)
        top.append(names)
        top.append(self.state_badge(item))
        box.append(top)
        if item.description or item.summary:
            text = Gtk.Label(label=item.description or item.summary, xalign=0, wrap=True, max_width_chars=1,
                             selectable=True)
            box.append(text)
        if item.state == "failed":
            self.settings_heading(box, _("Why it is not loaded"))
            self.note(box, item.reason)
        if item.state == "builtin":
            self.note(box, _("Part of Asterism itself: always there, nothing to install or remove for it."))
            if item.target:
                self.settings_heading(box, _("The program"))
                self.note(box, (_("{0} is installed on this PC.") if item.installed else
                                _("{0} is not installed on this PC.")).format(item.name))
        else:
            if item.key and item.installed is not None:
                self.settings_heading(box, _("The program"))
                self.note(box, (_("{0} is installed on this PC.") if item.installed else
                                _("{0} is not installed on this PC.")).format(item.name)
                          + ("" if item.state == "on" else " " + _("Switch the add-on on to install or remove it here.")))
            self.settings_heading(box, _("What it reads"))
            rows = self.boxed_list()
            for text in item.reads or [_("Nothing beyond what Asterism shows anyway.")]:
                rows.append(self.plain_row(text))
            box.append(rows)
            self.settings_heading(box, _("What it sends"))
            rows = self.boxed_list()
            for text in item.sends or [_("Nothing: it sends nothing anywhere.")]:
                rows.append(self.plain_row(text))
            box.append(rows)
            self.settings_heading(box, _("What it may do"))
            rows = self.boxed_list()
            rows.append(self.plain_row(_("Privacy level: {0}").format(privacy_name(item.privacy))))
            for capability in item.capabilities:
                rows.append(self.plain_row(capability_text(capability)))
            box.append(rows)
            self.note(box, _("Signed by Uwe Bruckhaus (key {0}). Asterism checks the signature and every file "
                             "before anything of it runs.").format("SHA256:e5cC634Ke3Our5LAeSc88qs22NKZEHTncBW5Ig3amWQ"))
        buttons = Gtk.Box(spacing=8, margin_top=6)
        back = Gtk.Button(label=_("All add-ons"))
        back.connect("clicked", lambda *_a: self.addons_stack.set_visible_child_name("list"))
        buttons.append(back)
        if item.homepage:
            buttons.append(self.homepage_button(item, small=False))
        actions = []
        if item.update:
            actions.append((_("Update"), self.update_addon, True))
        actions += {"suggested": [(_("Get add-on"), self.install_addon, True)],
                    "available": [(_("Install"), self.install_addon, True)],
                    "off": [(_("Switch on"), self.switch_addon_on, False)],
                    "on": [(_("Switch off"), self.switch_addon_off, False)]}.get(item.state, [])
        for label, run, suggested in actions:
            button = Gtk.Button(label=label)
            if suggested:
                button.add_css_class("suggested-action")
            button.connect("clicked", lambda *_a, r=run: r(item))
            buttons.append(button)
        if item.target:
            buttons.append(self.program_buttons(item, small=False))
        if item.state == "on" and not item.key:
            # A feature add-on made for an agent: install the program itself too.
            for command in (item.entry.harnesses if item.entry else []):
                h = harnesses.get(command)
                if h is not None and h.install and not any(a.command == command and a.installed
                                                           for a in self.agent_list):
                    button = Gtk.Button(label=_("Install {0} too").format(h.full_name or h.name))
                    button.add_css_class("suggested-action")
                    button.connect("clicked", lambda *_a, c=command: self.offer_install("agent", c))
                    buttons.append(button)
        if item.state in ("on", "off", "failed") and item.addon is not None:
            remove = Gtk.Button(label=_("Remove"))
            remove.add_css_class("destructive-action")
            remove.connect("clicked", lambda *_a: self.remove_addon(item))
            buttons.append(remove)
        box.append(buttons)
        self.addons_stack.set_visible_child_name("detail")

    # --- actions ---
    def addon_confirm(self, item: Item, heading: str, ok_label: str, on_ok):
        """Before switching an add-on on: what it reads, sends and may do."""
        lines = [privacy_name(item.privacy)] + [capability_text(c) for c in item.capabilities]
        body = _("{0} reads: {1}").format(item.name, "; ".join(item.reads) or _("nothing beyond what Asterism shows")) \
            + "\n\n" + _("It sends: {0}").format("; ".join(item.sends) or _("nothing")) + "\n\n" + " · ".join(lines)
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("ok", ok_label)
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.connect("response", lambda _d, response: response == "ok" and on_ok())
        dialog.present(self.window)

    def addons_changed(self, message: str = "", select: str = ""):
        self.reload_addons()
        if message:
            self.toast(message, 4)
        self.addons_select = select
        self.refresh_addons()

    def install_addon(self, item: Item):
        if item.entry is None:
            return

        def go():
            self.toast(_("Installing {0}…").format(item.name), 3)

            def work():
                try:
                    addon_store.install(item.entry)
                    addon_store.set_enabled(item.id, True)
                    return ""
                except addon_store.InstallError as error:
                    return str(error)

            def done(error):
                if error:
                    self.toast(_("{0} was not installed: {1}").format(item.name, error), 8)
                else:
                    self.addons_changed(_("{0} is installed and on.").format(item.name), item.id)
                return False
            threading.Thread(target=lambda: GLib.idle_add(done, work()), daemon=True).start()
        self.addon_confirm(item, _("Install {0}?").format(item.name), _("Install and switch on"), go)

    def update_addon(self, item: Item):
        if item.entry is None:
            return

        def work():
            try:
                addon_store.install(item.entry)
                return ""
            except addon_store.InstallError as error:
                return str(error)

        def done(error):
            if error:
                self.toast(_("{0} was not updated: {1}").format(item.name, error), 8)
            else:
                self.addons_changed(_("{0} is updated to {1}.").format(item.name, item.entry.version), item.id)
            return False
        self.toast(_("Updating {0}…").format(item.name), 3)
        threading.Thread(target=lambda: GLib.idle_add(done, work()), daemon=True).start()

    def switch_addon_on(self, item: Item):
        def go():
            addon_store.set_enabled(item.id, True)
            self.addons_changed(_("{0} is on.").format(item.name), item.id)
        self.addon_confirm(item, _("Switch on {0}?").format(item.name), _("Switch on"), go)

    def switch_addon_off(self, item: Item):
        addon_store.set_enabled(item.id, False)
        self.addons_changed(_("{0} is off.").format(item.name), item.id)

    def remove_addon(self, item: Item):
        dialog = Adw.AlertDialog(heading=_("Remove {0}?").format(item.name),
                                 body=_("It goes to the trash; you can install it again any time."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def answered(_d, response):
            if response != "remove":
                return
            if addon_store.remove(item.id):
                self.addons_changed(_("{0} is removed (in the trash).").format(item.name))
            else:
                self.toast(_("{0} is installed for every user; remove its package instead.").format(item.name), 8)
        dialog.connect("response", answered)
        dialog.present(self.window)

    # --- drag & drop: an add-on zip from a folder, or a link from the web, anywhere on the window ---
    def setup_addon_drop(self, window):
        target = Gtk.DropTarget.new(GObject.TYPE_NONE, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        target.set_gtypes([Gdk.FileList, GObject.TYPE_STRING])
        target.connect("drop", self.on_addon_drop)
        window.add_controller(target)

    def on_addon_drop(self, _target, value, _x, _y) -> bool:
        path = url = None
        if isinstance(value, Gdk.FileList):
            files = value.get_files()
            if files and files[0].get_path() and files[0].get_path().endswith(".zip"):
                path = files[0].get_path()
        elif isinstance(value, str):
            line = next((l.strip() for l in value.splitlines() if l.strip() and not l.startswith("#")), "")
            if line.startswith("file://") and line.endswith(".zip"):
                path = Gio.File.new_for_uri(line).get_path()
            elif line.startswith("https://") and line.endswith(".zip"):
                url = line
        if not path and not url:
            return False                      # not an add-on: let others handle it
        self.toast(_("Adding the add-on…"), 3)

        def work():
            try:
                addon = addon_store.install_file(Path(path)) if path else addon_store.install_url(url)
                return addon, ""
            except addon_store.InstallError as error:
                return None, str(error)

        def done(found):
            addon, error = found
            if addon is None:
                self.toast(_("Not installed: {0}").format(error), 8)
            else:
                self.reload_addons()
                self.open_addons(select=addon.id)
                self.toast(_("{0} is installed; switch it on on its card.").format(addon.name), 6)
            return False
        threading.Thread(target=lambda: GLib.idle_add(done, work()), daemon=True).start()
        return True

    def addon_from_file(self):
        dialog = Gtk.FileDialog(title=_("Install an add-on from a file"))
        zips = Gtk.FileFilter(name=_("Add-on (.zip)"))
        zips.add_pattern("*.zip")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(zips)
        dialog.set_filters(filters)

        def chosen(_dialog, result):
            try:
                file = dialog.open_finish(result)
            except GLib.Error:
                return
            path = file.get_path() if file is not None else None
            if not path:
                return
            try:
                addon = addon_store.install_file(Path(path))
            except addon_store.InstallError as error:
                self.toast(_("Not installed: {0}").format(error), 8)
                return
            self.addons_changed(_("{0} is installed; switch it on on its card.").format(addon.name), addon.id)
        dialog.open(self.window, None, chosen)
