"""AI Agents Map: small drawing and text helpers shared by the window's modules."""

from gi.repository import Gtk

from map_view import MapView


# Nerd Font glyphs for the cards of the pick lists (MCP servers, models, skills).
GLYPHS = {
    "folder": "\U000F024B", "web": "\U000F059F", "chrome": "\U000F02AF", "screen": "\U000F0379",
    "search": "\U000F0349", "git": "\U000F02A2", "github": "\U000F02A4", "code": "\U000F0169",
    "docs": "\U000F05DA", "clock": "\U000F0150", "brain": "\U000F09D1", "steps": "\U000F027B",
    "test": "\U000F0668", "package": "\U000F03D6", "cloud": "\U000F015F", "docker": "\U000F0868",
    "python": "\U000F0320", "node": "\U000F0399", "model": "\U000F01A7", "file": "\U000F0214",
    "app": "\U000F0614", "skill": "\U000F140B",
}
MCP_GLYPHS = {"filesystem": "folder", "git": "git", "fetch": "web", "playwright": "screen",
              "chrome-devtools": "chrome", "brave-search": "search", "github": "github", "context7": "docs",
              "time": "clock", "memory": "brain", "sequential-thinking": "steps", "everything": "test"}
MCP_GROUP_GLYPHS = {"files": "folder", "web": "web", "code": "code", "think": "brain"}
RUN_GLYPHS = {"npm": "node", "pypi": "python", "oci": "docker", "remote": "cloud"}


def glyph(name: str) -> str:
    return GLYPHS.get(name, GLYPHS["package"])


def glyph_label(name: str) -> Gtk.Label:
    """A card's icon: a Nerd Font glyph in the accent colour."""
    label = Gtk.Label(label=glyph(name), valign=Gtk.Align.CENTER)
    label.add_css_class("am-agent-icon")
    label.add_css_class("am-pick-glyph")
    return label


def pick_cards(listbox: Gtk.ListBox) -> Gtk.ListBox:
    """A list whose rows are cards (spaced, framed, the selected one in the accent colour)."""
    listbox.remove_css_class("boxed-list")
    listbox.add_css_class("am-pick-cards")
    return listbox


def size_text(n: int) -> str:
    """2490000000 -> "2.5 GB"."""
    for size, unit in ((1e12, "TB"), (1e9, "GB"), (1e6, "MB")):
        if n >= size:
            return f"{n / size:.1f} {unit}"
    return f"{max(0, n) // 1000} kB"


class SpaceBar(Gtk.DrawingArea):
    """One stacked bar: parts (label, bytes, colour name) side by side, as wide as their share.
    Hovering a part tells its name and size."""

    HEIGHT = 14

    def __init__(self, color, parts):
        super().__init__()
        self.color = color          # (name, alpha) -> rgba, the map's palette
        self.parts = [p for p in parts if p[1] > 0]
        self.spans = []
        self.set_content_height(self.HEIGHT)
        self.set_hexpand(True)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self.on_tooltip)
        self.set_draw_func(self.on_draw)

    def on_draw(self, _area, cr, width, height):
        total = sum(size for _l, size, _c in self.parts) or 1
        MapView.rounded(cr, 0, 0, width, height, 4)
        cr.set_source_rgba(*self.color("fg", 0.08))
        cr.fill()
        x, self.spans = 0.0, []
        for label, size, name in self.parts:
            w = max(2.0, width * size / total)
            cr.save()
            MapView.rounded(cr, 0, 0, width, height, 4)
            cr.clip()
            cr.rectangle(x, 0, w - (1 if x + w < width - 1 else 0), height)
            cr.set_source_rgba(*self.color(name, 0.9))
            cr.fill()
            cr.restore()
            self.spans.append((x, x + w, label, size))
            x += w

    def on_tooltip(self, _widget, x, _y, _keyboard, tooltip):
        for start, end, label, size in self.spans:
            if start <= x < end:
                tooltip.set_text(f"{label}: {size_text(size)}")
                return True
        return False
