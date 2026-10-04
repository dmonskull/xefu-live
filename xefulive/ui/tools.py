import os
import tkinter as tk
from tkinter import ttk

from .. import paths
from ..xbdm import discover
from .common import HEADING, MONO, AreaPicker, hex8, make_tree, open_folder


class ToolsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        pal = app.pal
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", anchor="n")
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))

        box = ttk.LabelFrame(left, text="Console", padding=10)
        box.pack(fill="x")
        row = ttk.Frame(box)
        row.pack(fill="x")
        self.host = tk.StringVar(value=app.s.config.get("host", ""))
        e = ttk.Entry(row, textvariable=self.host, width=18, font=MONO)
        e.pack(side="left")
        e.bind("<Return>", lambda ev: self.connect())
        ttk.Button(row, text="Connect", command=self.connect).pack(side="left", padx=6)
        ttk.Button(row, text="Find consoles", command=self.find).pack(side="left")
        self.found = ttk.Label(box, foreground=pal["dim"], text="")
        self.found.pack(anchor="w", pady=(6, 0))
        self.info = self._grid(box, (("console", "Console"), ("game", "Game"), ("title_id", "Title ID"),
                                     ("emulator", "Emulator"), ("ram", "Game RAM on the 360"), ("image", "XBE image")))
        self.pause_reads = tk.BooleanVar(value=app.s.pause_big_reads)
        ttk.Checkbutton(box, text="Pause the game during big reads (about 10x faster)",
                        variable=self.pause_reads, command=self._pause_reads_changed).pack(anchor="w", pady=(8, 0))

        box = ttk.LabelFrame(left, text="Address converter", padding=10)
        box.pack(fill="x", pady=(12, 0))
        row = ttk.Frame(box)
        row.pack(fill="x")
        self.conv = tk.StringVar()
        e = ttk.Entry(row, textvariable=self.conv, width=26, font=MONO)
        e.pack(side="left")
        e.bind("<Return>", lambda ev: self.convert())
        ttk.Button(row, text="Convert", command=self.convert).pack(side="left", padx=6)
        self.conv_out = self._grid(box, (("addr", "Game address"), ("host", "360 address"),
                                         ("phys", "Xbox physical"), ("section", "Section")))
        ttk.Label(box, foreground=pal["dim"], wraplength=380, justify="left", text=(
            "The 360 address works in any other XBDM tool. It can move when the game allocates memory, "
            "so convert again after loading a level.")).pack(anchor="w", pady=(6, 0))

        box = ttk.LabelFrame(left, text="Save memory to a file", padding=10)
        box.pack(fill="x", pady=(12, 0))
        self.area = AreaPicker(box, width=40)
        self.area.pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=(6, 0))
        ttk.Button(row, text="Save", command=self.dump).pack(side="left")
        ttk.Button(row, text="Show dumps folder", command=lambda: open_folder(paths.path("dumps"))).pack(side="left", padx=6)
        self.dump_out = ttk.Label(box, foreground=pal["dim"], wraplength=380, justify="left", text="")
        self.dump_out.pack(anchor="w", pady=(6, 0))

        ttk.Label(right, text="The game's XBE sections", font=HEADING).pack(anchor="w")
        frame, self.sections = make_tree(right, (
            ("name", "Section", 110, "w"), ("start", "Start", 100, "w"), ("end", "End", 100, "w"),
            ("size", "Size", 110, "e"), ("kind", "Kind", 120, "w")), height=10)
        frame.pack(fill="x", pady=(4, 0))
        self.sections.bind("<Double-1>", lambda e: self._view(self.sections))
        ttk.Label(right, text="Mapped memory", font=HEADING).pack(anchor="w", pady=(14, 0))
        frame, self.mapped = make_tree(right, (
            ("start", "Start", 100, "w"), ("end", "End", 100, "w"), ("size", "Size", 110, "e"),
            ("what", "What", 220, "w")), height=10)
        frame.pack(fill="both", expand=True, pady=(4, 0))
        self.mapped.bind("<Double-1>", lambda e: self._view(self.mapped))
        ttk.Label(right, foreground=pal["dim"], text="Double-click a row to open it in the Memory tab.").pack(anchor="w", pady=(6, 0))

    def _grid(self, parent, rows):
        out = {}
        grid = ttk.Frame(parent)
        grid.pack(anchor="w", pady=(6, 0))
        for i, (key, label) in enumerate(rows):
            ttk.Label(grid, text=label, foreground=self.app.pal["dim"]).grid(row=i, column=0, sticky="w", pady=1)
            out[key] = ttk.Label(grid, text="-", font=MONO)
            out[key].grid(row=i, column=1, sticky="w", padx=(12, 0))
        return out

    def _pause_reads_changed(self):
        self.app.s.pause_big_reads = self.pause_reads.get()
        # the time estimates in the area pickers depend on it
        for picker in (self.area, self.app.search.area, self.app.changes.area):
            self.app.tasks.run(self.app.s.areas, picker.set_areas)

    def on_game(self):
        s = self.app.s
        g, x = s.guest, s.guest.xbe
        self.info["console"].configure(text="%s (%s)" % (s.console_name, s.config.get("host", "")))
        self.info["game"].configure(text=x["title"])
        self.info["title_id"].configure(text=x["title_id"])
        self.info["emulator"].configure(text=g.emulator)
        self.info["ram"].configure(text="%s - %s" % (hex8(g.ram_base), hex8(g.ram_base + 0x04000000 - 1)))
        self.info["image"].configure(text="%s - %s" % (hex8(x["base"]), hex8(x["base"] + x["image_size"])))
        self.sections.delete(*self.sections.get_children())
        for sec in x["sections"]:
            kind = "data (writable)" if sec["writable"] and not sec["name"].startswith(".text") else "code / read-only"
            self.sections.insert("", "end", iid=str(sec["va"]), values=(
                sec["name"], hex8(sec["va"]), hex8(sec["va"] + sec["size"]), format(sec["size"], ","), kind))
        self.app.tasks.run(s.areas, self.area.set_areas)
        self.app.tasks.run(lambda: g.mapped(0x10000, 0x80000000), self._show_mapped)

    def _show_mapped(self, ranges):
        base = self.app.s.guest.xbe["base"]
        self.mapped.delete(*self.mapped.get_children())
        for a, b in ranges:
            self.mapped.insert("", "end", iid=str(a), values=(
                hex8(a), hex8(b), format(b - a, ","), "XBE image" if a == base else "heap"))

    def _view(self, tree):
        sel = tree.selection()
        if sel:
            self.app.goto(int(sel[0]))

    def connect(self):
        host = self.host.get().strip()
        self.app.say("Connecting...")
        self.app.tasks.run(lambda: self.app.s.connect(host), lambda _: self.app.poll_now())

    def find(self):
        self.found.configure(text="Looking for consoles on the network...")

        def done(found):
            if not found:
                return self.found.configure(text="No console answered. Check that XBDM is running on it.")
            self.found.configure(text="Found: " + ", ".join("%s (%s)" % (ip, name or "?") for ip, name in found))
            self.host.set(found[0][0])

        self.app.tasks.run(discover, done)

    def convert(self):
        expr = self.conv.get().strip()
        if not expr:
            return

        def done(d):
            self.conv_out["addr"].configure(text=hex8(d["addr"]))
            self.conv_out["host"].configure(text=hex8(d["host"]) if d["host"] is not None else "not mapped right now")
            self.conv_out["phys"].configure(text=hex8(d["phys"]) if d["phys"] is not None else "-")
            self.conv_out["section"].configure(text=d["section"] or "-")

        self.app.tasks.run(lambda: self.app.s.describe(self.app.s.need_game().resolve(expr)), done)

    def dump(self):
        area, lo, hi = self.area.get()

        def done(files):
            text = "Saved %d file%s in %s" % (len(files), "" if len(files) == 1 else "s", os.path.dirname(files[0]))
            self.dump_out.configure(text=text + "\n" + "\n".join(os.path.basename(p) for p in files[:12]))
            self.app.say(text)

        self.app.job("Saving memory to a file",
                     lambda progress: self.app.s.dump(self.app.s.regions(area, lo, hi), progress), done)
