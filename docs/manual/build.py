#!/usr/bin/env python3
"""Build the user manual PDF from manual.html.

    python3 docs/manual/build.py [--plugin-version 0.10.1] [--out FILE.pdf]

1. manual.html → build/manual.html: chapters and sections numbered, the contents page filled in,
   {{ASTERISM_VERSION}} / {{PLUGIN_VERSION}} / {{DATE}} replaced.
2. Chromium prints it to PDF. pdftotext tells on which page each heading landed; the contents page
   gets those numbers and is printed again until the numbers stay the same.
3. pdfcraft (pdfcraft-cli run --script) finishes it: document info, page labels (roman for the
   front matter, 1… from the first chapter), running header with the chapter title and a footer
   with the page number, bookmarks for every chapter and section, how it opens.

Needs chromium (or google-chrome), pdftotext (poppler) and pdfcraft-cli (PDFCRAFT=… or on PATH
or in ~/Applications/pdfcraft-*/).
"""
import argparse
import datetime
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BUILD = HERE / "build"
TITLE = "Asterism & AI Agents Map — User Manual"
AUTHOR = "Uwe Bruckhaus"
PLUGIN_MANIFEST = Path.home() / ".config/omarchy/plugins/ubruckhaus.ai-agents-map/manifest.json"


def asterism_version() -> str:
    text = (REPO / "packaging/aur/PKGBUILD").read_text()
    return re.search(r"^pkgver=(\S+)", text, re.M).group(1)


def plugin_version(given: str | None) -> str:
    if given:
        return given
    try:
        return json.loads(PLUGIN_MANIFEST.read_text())["version"]
    except (OSError, ValueError, KeyError):
        sys.exit(f"No AI Agents Map version: pass --plugin-version (no {PLUGIN_MANIFEST})")


def tool(name: str, env: str, candidates=()) -> str:
    found = os.environ.get(env) or shutil.which(name)
    for pattern in candidates:
        found = found or next(iter(sorted(glob.glob(os.path.expanduser(pattern)), reverse=True)), None)
    if not found:
        sys.exit(f"{name} not found (set {env})")
    return found


# --- 1. the HTML -------------------------------------------------------------------------------

CHAPTER = re.compile(r'<section class="chapter( appendix)?" id="([^"]+)">\s*<h1>(.*?)</h1>', re.S)
SECTION = re.compile(r'<h2 id="([^"]+)">(.*?)</h2>', re.S)


def plain(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def outline(source: str) -> list[dict]:
    """[{id, num, title, sections: [{id, num, title}]}] in document order."""
    chapters, starts = [], [m for m in CHAPTER.finditer(source)]
    number = 0
    for i, match in enumerate(starts):
        appendix = bool(match.group(1))
        number += 0 if appendix else 1
        num = "A" if appendix else str(number)
        end = starts[i + 1].start() if i + 1 < len(starts) else len(source)
        body = source[match.end():end]
        sections = [{"id": s.group(1), "num": f"{num}.{k}",
                     "title": plain(re.sub(r'<span class="badge[^"]*">.*?</span>', "", s.group(2)))}
                    for k, s in enumerate(SECTION.finditer(body), 1)]
        chapters.append({"id": match.group(2), "num": num, "title": plain(match.group(3)),
                         "appendix": appendix, "sections": sections})
    return chapters


def render_html(source: str, chapters: list, pages: dict, values: dict) -> str:
    out = source
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", html.escape(value))
    for ch in chapters:
        label = "Appendix" if ch["appendix"] else f"Chapter {ch['num']}"
        out = re.sub(rf'(<section class="chapter[^"]*" id="{re.escape(ch["id"])}">\s*)<h1>',
                     rf'\1<p class="chapter-label">{label}</p><h1>', out, count=1)
        for sec in ch["sections"]:
            out = out.replace(f'<h2 id="{sec["id"]}">', f'<h2 id="{sec["id"]}"><span class="sec">{sec["num"]}</span>', 1)
    toc = ["<ol>"]
    for ch in chapters:
        toc.append(f'<li class="toc-chapter"><a href="#{ch["id"]}"><span class="num">{ch["num"]}</span>'
                   f'<span class="title">{html.escape(ch["title"])}</span><span class="dots"></span>'
                   f'<span class="page">{pages.get(ch["id"], "00")}</span></a></li>')
        for sec in ch["sections"]:
            toc.append(f'<li class="toc-section"><a href="#{sec["id"]}"><span class="num">{sec["num"]}</span>'
                       f'<span class="title">{html.escape(sec["title"])}</span><span class="dots"></span>'
                       f'<span class="page">{pages.get(sec["id"], "00")}</span></a></li>')
    toc.append("</ol>")
    out = out.replace("<!-- TOC -->", "\n".join(toc))
    # Relative links (manual.css, images/) resolve from the source folder.
    return out.replace("<head>", f'<head>\n<base href="{HERE.as_uri()}/">', 1)


# --- 2. Chromium, and where the headings landed ----------------------------------------------------

def print_pdf(chromium: str, page: Path, pdf: Path):
    subprocess.run([chromium, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--run-all-compositor-stages-before-draw", "--virtual-time-budget=5000",
                    f"--print-to-pdf={pdf}", page.as_uri()],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def locate(pdf: Path, chapters: list) -> tuple[int, int, dict]:
    """(page count, physical page of chapter 1, {id: physical page}; "contents" too)."""
    text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], check=True, capture_output=True,
                          text=True).stdout
    pages = [squash(p) for p in text.split("\f")]
    if pages and not pages[-1]:
        pages.pop()
    body = next(i for i, p in enumerate(pages) if "chapter1" in p)
    found, at = {"contents": next(i for i in range(1, body) if pages[i].startswith("contents")) + 1}, body
    for ch in chapters:
        for item in [ch] + ch["sections"]:
            label = ("Appendix" if ch["appendix"] else f"Chapter {ch['num']}") if item is ch else item["num"]
            needle = squash(label + item["title"])[:40]
            while at < len(pages) and needle not in pages[at]:
                at += 1
            if at == len(pages):
                sys.exit(f"Heading not found in the PDF: {item['title']}")
            found[item["id"]] = at + 1
    return len(pages), body + 1, found


# --- 3. pdfcraft -------------------------------------------------------------------------------------

def finish(pdfcraft: str, raw: Path, out: Path, chapters: list, count: int, body: int, physical: dict,
           versions: str):
    steps = [{"tool": "doc_open", "args": {"path": str(raw)}}]
    for key, value in (("Title", TITLE), ("Author", AUTHOR),
                       ("Subject", "User manual for Asterism and the AI Agents Map Omarchy plugin"),
                       ("Keywords", "Asterism, AI Agents Map, Omarchy, coding agents, local LLM, MCP, skills"),
                       ("Creator", "Asterism docs/manual/build.py (Chromium, pdfcraft)")):
        steps.append({"tool": "doc_set_info", "args": {"doc": 1, "key": key, "value": value}})
    steps.append({"tool": "page_number", "args": {"doc": 1, "from": 1, "to": body - 1, "style": "lower-roman"}})
    steps.append({"tool": "page_number", "args": {"doc": 1, "from": body, "to": count, "style": "decimal"}})
    starts = [physical[ch["id"]] for ch in chapters] + [count + 1]
    for ch, first, nxt in zip(chapters, starts, starts[1:]):
        label = "Appendix" if ch["appendix"] else f"Chapter {ch['num']}"
        steps.append({"tool": "doc_header_footer", "args": {
            "doc": 1, "pages": list(range(first, nxt)), "start_number": first - body + 1,
            "header_left": "Asterism & AI Agents Map", "header_right": f"{label} · {ch['title']}",
            "footer_left": f"User Manual · {versions}", "footer_right": "<<1>>",
            "font_size": 7.5, "color": "#667085", "margins": [34, 30, 57, 57]}})
    steps.append({"tool": "bookmark_add", "args": {"doc": 1, "title": "About this manual", "page": 2}})
    steps.append({"tool": "bookmark_add", "args": {"doc": 1, "title": "Contents", "page": physical["contents"]}})
    for n, ch in enumerate(chapters, 3):
        steps.append({"tool": "bookmark_add", "args": {"doc": 1, "title": f"{ch['num']}  {ch['title']}",
                                                       "page": physical[ch["id"]]}})
        for sec in ch["sections"]:
            steps.append({"tool": "bookmark_add", "args": {"doc": 1, "parent": [n],
                                                           "title": f"{sec['num']}  {sec['title']}",
                                                           "page": physical[sec["id"]]}})
    steps.append({"tool": "doc_initial_view", "args": {"doc": 1, "navigation": "bookmarks", "display_title": True,
                                                       "language": "en", "layout": "continuous",
                                                       "magnification": "fit_width"}})
    steps.append({"tool": "doc_save", "args": {"doc": 1, "path": str(out), "full": True}})
    script = BUILD / "finish.json"
    script.write_text(json.dumps(steps, indent=1))
    result = subprocess.run([pdfcraft, "run", "--script", str(script), "--root", str(out.parent)],
                            capture_output=True, text=True, timeout=300)
    if result.returncode:
        sys.exit(f"pdfcraft failed:\n{result.stderr or result.stdout}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--plugin-version")
    parser.add_argument("--out", type=Path, default=BUILD / "Asterism-User-Manual.pdf")
    args = parser.parse_args()
    chromium = tool("chromium", "CHROMIUM", ("/usr/bin/google-chrome-stable",))
    pdfcraft = tool("pdfcraft-cli", "PDFCRAFT", ("~/Applications/pdfcraft-*/usr/bin/pdfcraft-cli",))
    BUILD.mkdir(exist_ok=True)
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    av, pv = asterism_version(), plugin_version(args.plugin_version)
    values = {"ASTERISM_VERSION": av, "PLUGIN_VERSION": pv,
              "DATE": datetime.date.today().strftime("%B %Y")}
    source = (HERE / "manual.html").read_text()
    chapters = outline(source)
    page, raw = BUILD / "manual.html", BUILD / "manual-raw.pdf"

    labels: dict = {}
    for _attempt in range(4):
        page.write_text(render_html(source, chapters, labels, values))
        print_pdf(chromium, page, raw)
        count, body, physical = locate(raw, chapters)
        new = {key: str(p - body + 1) for key, p in physical.items() if key != "contents"}
        if new == labels:
            break
        labels = new
    else:
        sys.exit("Page numbers did not settle")

    # pdfcraft works inside build/ only (its --root); the result is copied to --out from there.
    built = BUILD / "Asterism-User-Manual.pdf"
    finish(pdfcraft, raw, built, chapters, count, body, physical, f"Asterism {av} · AI Agents Map {pv}")
    if out != built.resolve():
        shutil.copyfile(built, out)
    # The copy the app opens from Help (data/ here; tools/vendor-into-plugin.sh puts it into the
    # plugin's assets/). The marketplace scan reads a file over 512 KiB only up to its first 4 KiB
    # and accepts it as a (non-executable) binary only when that part holds a NUL byte; a smaller
    # binary or one without that NUL fails the scan, so stop here instead of in review.
    data = built.read_bytes()
    if len(data) <= 512 * 1024 or b"\0" not in data[:4096]:
        sys.exit(f"{built}: {len(data)} bytes, NUL in the first 4 KiB: {b'\0' in data[:4096]} — the marketplace "
                 "scan would refuse it as an app asset (needs > 512 KiB and a NUL in the first 4 KiB)")
    shutil.copyfile(built, REPO / "data/user-manual.pdf")
    print(f"{out} — {count} pages, chapter 1 on page {body}")


if __name__ == "__main__":
    main()
