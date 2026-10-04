import sys
import tkinter as tk
from tkinter import ttk

from .. import values
from .common import HEADING, MONO, hex8

HEX = "0123456789abcdef"
SHOWN = (("u8", "Byte"), ("u16", "2 bytes"), ("u32", "4 bytes"), ("i32", "4 bytes, signed"),
         ("float", "Float"), ("double", "Double"), ("u32_hex", "4 bytes (hex)"), ("text", "Text"))


class MemoryTab(ttk.Frame):
    """Live hex view. Click a byte and type hex digits to change it in the game."""

    ROWS = 24
    HEX_COL = 10        # text column of the first hex byte
    ASCII_COL = 60

    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.addr = 0x10000
        self.data = b""
        self.mapped = []
        self.sel = None
        self.first = {}         # address -> byte value the first time we read it
        self.prev = None
        self.shown_addr = None
        self.nibble = None
        self.loading = False
        self.sections = []

        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Label(bar, text="Address").pack(side="left")
        self.addr_var = tk.StringVar(value="10000")
        entry = ttk.Entry(bar, textvariable=self.addr_var, width=26, font=MONO)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self.go())
        ttk.Button(bar, text="Go", command=self.go).pack(side="left")
        ttk.Button(bar, text="<", width=3, command=lambda: self.page(-1)).pack(side="left", padx=(10, 0))
        ttk.Button(bar, text=">", width=3, command=lambda: self.page(1)).pack(side="left")
        self.section = ttk.Combobox(bar, state="readonly", width=24)
        self.section.pack(side="left", padx=10)
        self.section.bind("<<ComboboxSelected>>", lambda e: self._jump_section())
        self.live = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Live", variable=self.live).pack(side="left")
        self.show_diff = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show changes since first read", variable=self.show_diff,
                        command=self.render).pack(side="left", padx=(14, 0))
        ttk.Button(bar, text="Use current as first read", command=self.mark_first).pack(side="left", padx=8)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=(10, 0))
        self.text = tk.Text(body, width=77, height=self.ROWS + 1, font=MONO, wrap="none", cursor="arrow",
                            borderwidth=0, highlightthickness=1, padx=8, pady=6, takefocus=1)
        self.text.pack(side="left", fill="y")
        pal = app.pal
        for tag in ("head", "addr", "zero", "unmapped"):
            self.text.tag_configure(tag, foreground=pal["dim"])
        self.text.tag_configure("flash", background=pal["flash_bg"])
        self.text.tag_configure("diff", background=pal["diff_bg"], foreground=pal["diff_fg"])
        self.text.tag_configure("sel", background=pal["sel_bg"], foreground=pal["sel_fg"])
        self.text.tag_raise("sel")
        self.text.bind("<Button-1>", self._click)
        self.text.bind("<Key>", self._key)
        self.text.bind("<MouseWheel>", lambda e: self._wheel(-1 if e.delta > 0 else 1))
        self.text.bind("<Button-4>", lambda e: self._wheel(-1))     # X11 sends buttons, not MouseWheel
        self.text.bind("<Button-5>", lambda e: self._wheel(1))
        self.text.configure(state="disabled")

        side = ttk.Frame(body, padding=(16, 0, 0, 0))
        side.pack(side="left", fill="both", expand=True)
        ttk.Label(side, text="Selected byte", font=HEADING).grid(row=0, column=0, columnspan=2, sticky="w")
        self.where = {}
        self.vals = {}
        row = 1
        for key, label in (("addr", "Game address"), ("host", "360 address"), ("section", "Section")):
            ttk.Label(side, text=label, foreground=pal["dim"]).grid(row=row, column=0, sticky="w", pady=1)
            self.where[key] = ttk.Label(side, text="", font=MONO)
            self.where[key].grid(row=row, column=1, sticky="w", padx=(12, 0))
            row += 1
        ttk.Separator(side).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        for key, label in SHOWN:
            ttk.Label(side, text=label, foreground=pal["dim"]).grid(row=row, column=0, sticky="w", pady=1)
            self.vals[key] = ttk.Label(side, text="", font=MONO)
            self.vals[key].grid(row=row, column=1, sticky="w", padx=(12, 0))
            row += 1
        ttk.Separator(side).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        ttk.Label(side, text="Write a value here", font=HEADING).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        write = ttk.Frame(side)
        write.grid(row=row, column=0, columnspan=2, sticky="w", pady=6)
        self.poke_type = ttk.Combobox(write, state="readonly", width=18, values=[values.LABELS[t] for t in values.ALL])
        self.poke_type.current(values.ALL.index("float"))
        self.poke_type.pack(side="left")
        self.poke_value = tk.StringVar()
        e = ttk.Entry(write, textvariable=self.poke_value, width=16, font=MONO)
        e.pack(side="left", padx=6)
        e.bind("<Return>", lambda ev: self.poke())
        ttk.Button(write, text="Write", command=self.poke).pack(side="left")
        row += 1
        buttons = ttk.Frame(side)
        buttons.grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Button(buttons, text="Add to mods...", command=self.add_mod).pack(side="left")
        ttk.Button(buttons, text="Copy address", command=self.copy).pack(side="left", padx=6)
        row += 1
        ttk.Label(side, wraplength=330, foreground=pal["dim"], justify="left", text=(
            "Click a byte and type hex digits to change it in the running game. Arrow keys move, "
            "Page Up and Page Down scroll.\n\nAddresses are the game's own, the same ones Ghidra shows "
            "for the XBE. A saved name or a formula works too, like BB85B8 + 2*6140 or [C01234] + 10."
        )).grid(row=row, column=0, columnspan=2, sticky="w", pady=(14, 0))
        self.after(1000, self._tick)

    def on_game(self):
        x = self.app.s.guest.xbe
        self.sections = [(s["name"], s["va"]) for s in x["sections"]]
        self.section["values"] = ["Jump to section..."] + ["%s  %s" % (hex8(va), name) for name, va in self.sections]
        self.section.current(0)
        self.first = {}
        self.prev = None
        self.data = b""
        self.show(x["base"], top=True)

    def _jump_section(self):
        i = self.section.current()
        if i > 0:
            self.show(self.sections[i - 1][1], top=True)
        self.section.current(0)

    def go(self):
        expr = self.addr_var.get().strip()
        if expr:
            self.app.tasks.run(lambda: self.app.s.need_game().resolve(expr), self.show)

    def show(self, addr, top=False):
        addr &= 0xFFFFFFFF
        self.sel = addr
        self.nibble = None
        if top:
            self.addr = addr & ~0xF
        elif not (self.addr <= addr < self.addr + self.ROWS * 16 and self.data):
            self.addr = max(0, (addr & ~0xF) - 0x40)
        self.addr_var.set(hex8(addr))
        self.refresh()

    def page(self, direction, rows=None):
        step = (rows or self.ROWS) * 16 * direction
        self.addr = min(max(0, self.addr + step), 0xFFFFFFFF - self.ROWS * 16 + 1) & ~0xF
        self.refresh()

    def _wheel(self, direction):
        self.page(direction, rows=3)
        return "break"

    def _tick(self):
        if self.live.get() and self.app.visible(self) and self.app.s.running and not self.app.busy:
            self.refresh()
        self.after(1000, self._tick)

    def refresh(self):
        if self.loading or not self.app.s.running:
            return
        self.loading = True
        addr, size = self.addr, self.ROWS * 16

        def work():
            g = self.app.s.need_game()
            g.refresh_tables()
            mapped = []
            for _, host, n in g.spans(addr, size):
                mapped += [host is not None] * n
            return addr, g.read(addr, size, fill=b"\0"), mapped

        def done(result):
            self.loading = False
            got_addr, data, mapped = result
            if got_addr != self.addr:       # the user scrolled while we were reading
                return self.refresh()
            self.prev = self.data if self.data and self.shown_addr == got_addr else None
            self.data, self.mapped, self.shown_addr = data, mapped, got_addr
            for i, b in enumerate(data):
                if mapped[i]:
                    self.first.setdefault(got_addr + i, b)
            self.render()

        def fail(err):
            self.loading = False
            self.app.fail(err)

        self.app.tasks.run(work, done, fail)

    def mark_first(self):
        self.first = {self.addr + i: b for i, b in enumerate(self.data) if self.mapped[i]}
        self.render()
        self.app.say("Comparing against the memory as it is right now.")

    def _cols(self, i):
        return self.HEX_COL + i * 3 + (1 if i >= 8 else 0), self.ASCII_COL + i

    def render(self):
        data = self.data
        if not data:
            return
        lines = ["Address   " + " ".join("%02X" % i for i in range(8)) + "  " +
                 " ".join("%02X" % i for i in range(8, 16)) + "  0123456789ABCDEF"]
        for r in range(self.ROWS):
            row = data[r * 16:r * 16 + 16]
            ok = self.mapped[r * 16:r * 16 + 16]
            cells = ["%02X" % b if m else "--" for b, m in zip(row, ok)]
            text = "".join(chr(b) if m and 32 <= b < 127 else "." if m else " " for b, m in zip(row, ok))
            lines.append("%s  %s  %s  %s" % (hex8(self.addr + r * 16), " ".join(cells[:8]), " ".join(cells[8:]), text))
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", "\n".join(lines))
        t.tag_add("head", "1.0", "1.end")
        diff_on = self.show_diff.get()
        changed = 0
        for i, b in enumerate(data):
            line = i // 16 + 2
            hc, ac = self._cols(i % 16)
            tag = None
            if not self.mapped[i]:
                tag = "unmapped"
            elif diff_on and self.first.get(self.addr + i, b) != b:
                tag = "diff"
                changed += 1
            elif self.prev is not None and self.prev[i] != b:
                tag = "flash"
            elif b == 0:
                tag = "zero"
            if tag:
                t.tag_add(tag, "%d.%d" % (line, hc), "%d.%d" % (line, hc + 2))
                if tag in ("diff", "flash"):
                    t.tag_add(tag, "%d.%d" % (line, ac), "%d.%d" % (line, ac + 1))
        for r in range(self.ROWS):
            t.tag_add("addr", "%d.0" % (r + 2), "%d.8" % (r + 2))
        if self.sel is not None and self.addr <= self.sel < self.addr + len(data):
            i = self.sel - self.addr
            line = i // 16 + 2
            hc, ac = self._cols(i % 16)
            t.tag_add("sel", "%d.%d" % (line, hc), "%d.%d" % (line, hc + 2))
            t.tag_add("sel", "%d.%d" % (line, ac), "%d.%d" % (line, ac + 1))
        t.configure(state="disabled")
        if diff_on:
            self.app.say("%d byte%s on this page differ from the first read." % (changed, "" if changed == 1 else "s"))
        self._inspect()

    def _inspect(self):
        if self.sel is None or not (self.addr <= self.sel < self.addr + len(self.data)):
            return
        g = self.app.s.guest
        i = self.sel - self.addr
        shown = values.show_all(self.data[i:i + 16].ljust(16, b"\0"))
        host = g.host(self.sel)
        self.where["addr"].configure(text=hex8(self.sel))
        self.where["host"].configure(text=hex8(host) if host is not None else "not mapped",
                                     foreground=self.app.pal["bad"] if host is None else "")
        self.where["section"].configure(text=g.section_of(self.sel) or "-")
        for key, _ in SHOWN:
            self.vals[key].configure(text=str(shown[key]))
        first = self.first.get(self.sel)
        if first is not None and first != self.data[i]:
            self.vals["u8"].configure(text="%s   (was %d / %02X at first read)" % (shown["u8"], first, first))

    def _click(self, event):
        self.text.focus_set()
        line, col = map(int, self.text.index("@%d,%d" % (event.x, event.y)).split("."))
        row = line - 2
        if not 0 <= row < self.ROWS:
            return "break"
        if col >= self.ASCII_COL:
            i = col - self.ASCII_COL
        elif col >= self.HEX_COL:
            c = col - self.HEX_COL
            i = (c - 1) // 3 if c >= 25 else c // 3
        else:
            i = 0
        if 0 <= i < 16:
            self.sel = self.addr + row * 16 + i
            self.nibble = None
            self.addr_var.set(hex8(self.sel))
            self.render()
        return "break"

    def _move(self, delta):
        if self.sel is None:
            return
        self.sel = min(max(0, self.sel + delta), 0xFFFFFFFF)
        self.nibble = None
        self.addr_var.set(hex8(self.sel))
        if self.sel < self.addr:
            self.page(-1, rows=-(-(self.addr - self.sel) // 16))
        elif self.sel >= self.addr + self.ROWS * 16:
            self.page(1, rows=(self.sel - self.addr) // 16 - self.ROWS + 1)
        else:
            self.render()

    def _key(self, event):
        moves = {"Left": -1, "Right": 1, "Up": -16, "Down": 16}
        # leave shortcuts alone: Control everywhere, Command on a Mac
        shortcut = event.state & 0x4 or (sys.platform == "darwin" and event.state & 0x8)
        if event.keysym in moves:
            self._move(moves[event.keysym])
        elif event.keysym == "Prior":
            self.page(-1)
        elif event.keysym == "Next":
            self.page(1)
        elif event.keysym == "Escape":
            self.nibble = None
        elif event.char and event.char.lower() in HEX and self.sel is not None and not shortcut:
            digit = HEX.index(event.char.lower())
            if self.nibble is None:
                self.nibble = digit
                self.app.say("Typing byte %X_ at %s (one more hex digit, Esc cancels)" % (digit, hex8(self.sel)))
            else:
                value, addr = (self.nibble << 4) | digit, self.sel
                self.nibble = None
                self._write(addr, bytes([value]), advance=True)
        return "break"

    def _write(self, addr, data, advance=False):
        def done(_):
            self.app.say("Wrote %s at %s" % (data.hex(" ").upper(), hex8(addr)))
            if advance:
                self.sel = addr + len(data)
                self.addr_var.set(hex8(self.sel))
            self.refresh()

        self.app.tasks.run(lambda: self.app.s.need_game().write(addr, data), done)

    def poke(self):
        if self.sel is None:
            return self.app.say("Click a byte first.")
        vtype = values.ALL[self.poke_type.current()]
        try:
            data = values.encode(vtype, self.poke_value.get())
        except ValueError as e:
            return self.app.fail(e)
        if vtype == "text":
            data += b"\0"
        elif vtype == "text16":
            data += b"\0\0"
        self._write(self.sel, data)

    def add_mod(self):
        if self.sel is not None:
            self.app.add_mod(hex8(self.sel), values.ALL[self.poke_type.current()])

    def copy(self):
        if self.sel is not None:
            self.clipboard_clear()
            self.clipboard_append(hex8(self.sel))
            self.app.say("Copied %s" % hex8(self.sel))
