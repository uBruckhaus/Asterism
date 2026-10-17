# Asterism

Your AI agents, models and tools on one map: a GTK 4 / libadwaita app.

Asterism shows the AI setup on your computer as cards and a map:

- **coding agents** (Claude Code, Codex, Copilot, Cursor CLI, Gemini, OpenCode, Pi, …) with their
  plan, limits, usage and what each still needs, with the command that fixes it;
- **local LLMs** (llama.cpp, Ollama, LM Studio, vLLM, Jan, KoboldCpp) and their models: install
  them (every download checked against its release's SHA-256), download models, set the context
  size that fits your graphics card, start them with their agents;
- **MCP servers and skills**, found on your computer or on the web;
- a **health check**: what works, what to fix, what the setup is good for.

Connect an agent to a local LLM, an MCP server or a skill folder by drawing a line on the map:
a preview shows every change first, and Undo puts it back.

On [Omarchy](https://omarchy.org) the same app is the **AI Agents Map** plugin (bar icon, Omarchy
theme, Hyprland window actions). Install that one there.

## Install

- **Arch Linux (AUR):** `asterism` (`packaging/aur/PKGBUILD`).
- **AppImage:** `Asterism-<version>-x86_64.AppImage` from the releases. It uses your distribution's
  Python 3 with PyGObject, GTK 4 and libadwaita:
  - Fedora: `sudo dnf install python3-gobject gtk4 libadwaita`
  - Ubuntu/Debian: `sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1`
  - Arch: `sudo pacman -S python-gobject gtk4 libadwaita`

  Agent icons need a Nerd Font (Symbols Nerd Font). Optional: `vte4` for agents in a terminal
  inside the window.
- **From source:** `bin/asterism` in a checkout.

Settings live in `~/.config/asterism/`. Light or dark and the accent colour follow your system.

## Privacy

Asterism never asks for root. It reads your agents' settings (never their credential files) and
your own processes, and contacts the web only for what you ask (searching models, MCP servers or
skills, installing) plus an update check every few hours (npm, the release pages of what it
installed, `mise outdated`). Every program runs without a shell, every answer with a size and
time limit.

**Claude Code's details** read its session files (`~/.claude/projects`), bounded and incremental:

- per project, numbers only (tokens, working time, sessions, lines changed, API value) from its
  replies and cost summaries; no message text;
- **Topics:** the title Claude Code gave each session (its own `ai-title` lines, nothing else of
  the conversation), cached owner-only in `~/.cache`;
- **Summarize with Claude…** (only on a click, after showing exactly what is sent): those titles and
  numbers, never the conversations, go to your own `claude -p`, which runs in plan mode without
  MCP servers or a saved session, in an empty folder.

(The AI Agents Map plugin shows only the numbers; titles and the summary are Asterism's.)

## Development

`python3 -m unittest discover -s tests`. `ASTERISM_DESKTOP=omarchy|generic` picks the desktop
integration. `tools/vendor-into-plugin.sh <plugin checkout>` copies a release into the Omarchy
plugin.

## License

MIT
