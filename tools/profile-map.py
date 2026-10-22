#!/usr/bin/env python3
"""What the map costs, measured instead of guessed.

    tools/profile-map.py                         the real MapView and FlowLayer on a made-up map with
                                                 working agents, drawn offscreen by GTK's own renderer:
                                                 milliseconds a frame and CPU at FlowLayer.FLOW_FPS
    tools/profile-map.py --agents 5 --scale 2 --renderer gl
    tools/profile-map.py --budget-ms 2           exit 1 when a frame of the lights costs more
    uwsm app -- tools/profile-map.py live        Asterism itself with a sampler on its GTK thread:
                                                 every 10 s, its CPU and which Python ran (the rest is
                                                 GTK's own code), appended to --out

The offscreen run opens no window and draws nothing on the screen; it needs a display only for the
GPU renderers (--renderer cairo works without one). `live` starts the app as bin/asterism does:
quit a running Asterism first (it is single-instance, a second start only raises the first), and
agents running in its terminal tabs end with it.

Measured on 2026-10-22 (4K at scale 2, one agent working): the whole app ~47 % of a core before the
lights were drawn as small images and textures at 30 frames a second, ~8-11 % after; ~1 % with no
agent working.
"""

from __future__ import annotations

import argparse
import collections
import os
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def made_up_graph(agents: int):
    """`agents` running agents, each on a local LLM of its own with one model, plus idle ones."""
    import graph
    g = graph.Graph()
    for i in range(agents + 2):
        running = "running" if i < agents else ""
        g.add(graph.Node(f"agent:a{i}", 1, f"Agent {i}", kind="agent", status=running))
        g.add(graph.Node(f"runtime:r{i}", 2, f"Runtime {i}", kind="runtime", status="running"))
        g.add(graph.Node(f"model:runtime:r{i}:m", 3, f"model-{i}-27B-Q4_K_M", kind="model"))
        g.link(f"agent:a{i}", f"runtime:r{i}", "uses")
        g.link(f"runtime:r{i}", f"model:runtime:r{i}:m", "serves")
        g.link(f"agent:a{i}", f"model:runtime:r{i}:m", "default")
    return g


def offscreen(args) -> int:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gsk", "4.0")
    from gi.repository import Gdk, Graphene, Gsk, Gtk
    import map_view
    import palette
    import usage_box

    Gtk.init()
    display = Gdk.Display.get_default()
    width, height, scale = args.width, args.height, args.scale

    view = map_view.MapView()
    view.set_palette({**palette.DEFAULT_COLORS, "outside": palette.outside_color(palette.DEFAULT_COLORS)}, 8)
    for name, value in (("get_width", width), ("get_height", height), ("get_scale_factor", scale)):
        setattr(view, name, lambda value=value: value)
    layer = map_view.FlowLayer(view)
    layer.get_scale_factor = lambda: scale
    view.flow_layer = layer
    view.set_graph(made_up_graph(args.agents), ["", "Agents", "Providers", "Models"])
    view.set_usage_box({f"agent:a{i}": usage_box.Reading(55.0, 400, 1000, "m") for i in range(args.agents)})

    renderer = getattr(Gsk, {"vulkan": "VulkanRenderer", "gl": "GLRenderer", "cairo": "CairoRenderer"}[args.renderer]).new()
    renderer.realize_for_display(display)
    viewport = Graphene.Rect().init(0, 0, width, height)
    try:
        def frame():
            snapshot = Gtk.Snapshot()
            snapshot.scale(scale, scale)
            view.do_snapshot(snapshot)            # the map: its texture after the first frame
            layer.do_snapshot(snapshot)           # the lights
            return snapshot.to_node()

        started = time.perf_counter()
        frame()                                   # the map's first drawing; tells the layer its paths
        first = time.perf_counter() - started
        layer.levels = {agent: 1.0 for agent in layer.paths}
        if not layer.levels:
            print("no lights: no agent's line was drawn (animations off in this desktop?)", file=sys.stderr)
            return 2
        for _ in range(10):
            renderer.render_texture(frame(), Graphene.Rect().init(0, 0, width * scale, height * scale))
        builds, renders = [], []
        for _ in range(args.frames):
            started = time.perf_counter()
            node = frame()
            built = time.perf_counter()
            renderer.render_texture(node, Graphene.Rect().init(0, 0, width * scale, height * scale))
            builds.append(built - started)
            renders.append(time.perf_counter() - built)
        empty = Gtk.Snapshot()
        empty.append_color(Gdk.RGBA(), viewport)
        empty = empty.to_node()
        bases = []
        for _ in range(args.frames // 4 or 1):
            started = time.perf_counter()
            renderer.render_texture(empty, Graphene.Rect().init(0, 0, width * scale, height * scale))
            bases.append(time.perf_counter() - started)
    finally:
        renderer.unrealize()

    ms = lambda values: statistics.median(values) * 1000
    build, render, base = ms(builds), ms(renders), ms(bases)
    per_frame = build + max(0.0, render - base)
    fps = map_view.FlowLayer.FLOW_FPS
    print(f"map {width}x{height} at scale {scale}, {args.agents} agents working, {args.renderer} renderer")
    print(f"  map drawing (once, then a texture): {first * 1000:6.1f} ms")
    print(f"  a frame of the lights, Python:      {build:6.2f} ms")
    print(f"  a frame, GTK's renderer:            {max(0.0, render - base):6.2f} ms  "
          f"(an empty frame's {base:.2f} ms of reading back left out)")
    print(f"  at {fps} frames a second:              {per_frame * fps / 10:6.1f} % of a core")
    if args.budget_ms is not None and per_frame > args.budget_ms:
        print(f"OVER BUDGET: {per_frame:.2f} ms a frame > {args.budget_ms} ms", file=sys.stderr)
        return 1
    return 0


def live(args) -> int:
    """Asterism as bin/asterism starts it, with a sampler on the GTK main thread."""
    os.environ.setdefault("ASTERISM_DESKTOP", "generic")
    out = Path(args.out)
    main = threading.main_thread().ident
    ticks = os.sysconf("SC_CLK_TCK")

    def thread_cpu() -> float:
        stat = Path(f"/proc/self/task/{os.getpid()}/stat").read_text()
        fields = stat[stat.rindex(")") + 2:].split()
        return (int(fields[11]) + int(fields[12])) / ticks

    def sampler():
        leaves = collections.Counter()
        samples = in_gtk = 0
        since, cpu = time.monotonic(), thread_cpu()
        while True:
            time.sleep(0.001)
            frame = sys._current_frames().get(main)
            stack = []
            while frame is not None:
                stack.append(frame.f_code)
                frame = frame.f_back
            samples += 1
            # The innermost Python frame is Gio.Application.run while GTK runs its own code (or waits).
            if not stack or stack[0].co_name == "run" and stack[0].co_filename.endswith("Gio.py"):
                in_gtk += 1
            else:
                leaves[f"{Path(stack[0].co_filename).name}:{stack[0].co_name}"] += 1
            now = time.monotonic()
            if now - since >= 10:
                used = (thread_cpu() - cpu) / (now - since) * 100
                lines = [f"== {time.strftime('%H:%M:%S')}  GTK thread {used:.0f}% of a core, Python running in "
                         f"{100 * (samples - in_gtk) / samples:.1f}% of {samples} samples"]
                lines += [f"   in      {100 * n / samples:5.1f}%  {k}" for k, n in leaves.most_common(10)]
                with out.open("a") as handle:
                    handle.write("\n".join(lines) + "\n")
                leaves.clear()
                samples = in_gtk = 0
                since, cpu = now, thread_cpu()

    sys.setswitchinterval(0.001)              # the sampler gets its turn soon while Python runs
    sys.argv = [str(ROOT / "ai_popup.py")]
    import ai_popup
    import map_view
    if args.fps:
        map_view.FlowLayer.FLOW_FPS = args.fps
    with out.open("a") as handle:
        handle.write(f"## {time.strftime('%Y-%m-%d %H:%M:%S')} Asterism started, lights at "
                     f"{map_view.FlowLayer.FLOW_FPS} frames a second\n")
    print(f"sampling into {out}", file=sys.stderr)
    threading.Thread(target=sampler, daemon=True, name="profiler").start()
    return ai_popup.main()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="mode")
    run = sub.add_parser("live", help="start Asterism with a sampler on its GTK thread")
    run.add_argument("--fps", type=int, help="the lights' frame rate (instead of FlowLayer.FLOW_FPS)")
    run.add_argument("--out", default=os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp",
                                                   "asterism-profile.txt"))
    parser.add_argument("--agents", type=int, default=1)
    parser.add_argument("--width", type=int, default=1366)
    parser.add_argument("--height", type=int, default=1452)
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--renderer", choices=("vulkan", "gl", "cairo"), default="vulkan")
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--budget-ms", type=float)
    args = parser.parse_args()
    return live(args) if args.mode == "live" else offscreen(args)


if __name__ == "__main__":
    sys.exit(main())
