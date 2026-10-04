import tkinter as tk
from tkinter import ttk

from .. import values
from ..scanner import FIRST, MultiScan, Scan
from .common import MONO, AreaPicker, Form, hex8, make_tree, size_text

COMPARES = (
    ("is exactly", "eq"),
    ("is not", "ne"),
    ("is bigger than", "gt"),
    ("is smaller than", "lt"),
    ("is between", "between"),
    ("could be anything (unknown value)", "unknown"),
    ("changed since the last scan", "changed"),
    ("did not change since the last scan", "unchanged"),
    ("went up since the last scan", "increased"),
    ("went down since the last scan", "decreased"),
    ("went up by exactly", "incby"),
    ("went down by exactly", "decby"),
)
NEEDS_VALUE = ("eq", "ne", "gt", "lt", "between", "incby", "decby")
TYPE_IDS = ("any",) + values.ALL
TYPE_LABELS = ["Number (any type)"] + [values.LABELS[t] for t in values.ALL]
MAX_ROWS = 500
LIVE_ROWS = 150
START_HINT = ("Type the number you see in the game and run a first scan. Change it in the game, "
              "type the new number, run a next scan.")


class SearchTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.scan = None
        self.rows = []
        self.history = []       # (comparison, typed value, matches) for each scan so far
        self.loading = False

        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text="Type").pack(side="left")
        self.type_box = ttk.Combobox(row, state="readonly", width=18, values=TYPE_LABELS)
        self.type_box.current(0)
        self.type_box.pack(side="left", padx=(6, 14))
        ttk.Label(row, text="Find values that").pack(side="left")
        self.cmp_box = ttk.Combobox(row, state="readonly", width=32, values=[c[0] for c in COMPARES])
        self.cmp_box.current(0)
        self.cmp_box.pack(side="left", padx=6)
        self.cmp_box.bind("<<ComboboxSelected>>", lambda e: self._cmp_changed())
        self.value = tk.StringVar()
        self.value_entry = ttk.Entry(row, textvariable=self.value, width=16, font=MONO)
        self.value_entry.pack(side="left")
        self.value_entry.bind("<Return>", lambda e: self.next_scan() if self.scan else self.first_scan())
        self.and_label = ttk.Label(row, text="and")
        self.value2 = tk.StringVar()
        self.value2_entry = ttk.Entry(row, textvariable=self.value2, width=16, font=MONO)

        row = ttk.Frame(self)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Look in").pack(side="left")
        self.area = AreaPicker(row)
        self.area.pack(side="left", padx=6)
        self.aligned = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Aligned addresses only (faster)", variable=self.aligned).pack(side="left", padx=10)

        row = ttk.Frame(self)
        row.pack(fill="x", pady=(10, 6))
        self.first_btn = ttk.Button(row, text="First scan", command=self.first_scan)
        self.first_btn.pack(side="left")
        self.next_btn = ttk.Button(row, text="Next scan", command=self.next_scan, state="disabled")
        self.next_btn.pack(side="left", padx=6)
        self.reset_btn = ttk.Button(row, text="New search", command=self.reset, state="disabled")
        self.reset_btn.pack(side="left")
        self.live = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Live values", variable=self.live).pack(side="left", padx=14)

        self.summary = ttk.Label(self, text=START_HINT, foreground=app.pal["dim"])
        self.summary.pack(fill="x", pady=(0, 2))
        self.trail = ttk.Label(self, text="", foreground=app.pal["dim"])
        self.trail.pack(fill="x", pady=(0, 6))

        frame, self.tree = make_tree(self, (
            ("addr", "Address", 110, "w"), ("type", "Type", 130, "w"), ("now", "In the game now", 180, "w"),
            ("last", "At this scan", 180, "w"), ("before", "At the scan before", 180, "w")), height=17)
        frame.pack(fill="both", expand=True)
        self.tree.configure(selectmode="extended")
        self.tree.bind("<Double-1>", lambda e: self.view())
        self.tree.tag_configure("changed", foreground=app.pal["warn"])

        row = ttk.Frame(self)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="View in Memory", command=self.view).pack(side="left")
        ttk.Button(row, text="Set value...", command=self.set_value).pack(side="left", padx=6)
        ttk.Button(row, text="Add to mods...", command=self.add_mod).pack(side="left")
        self.after(1500, self._tick)

    def on_game(self):
        self.reset()
        self.app.tasks.run(self.app.s.areas, self.area.set_areas)

    def _cmp(self):
        return COMPARES[self.cmp_box.current()][1]

    def _cmp_changed(self):
        cmp = self._cmp()
        if cmp == "between":
            self.and_label.pack(side="left", padx=6)
            self.value2_entry.pack(side="left")
        else:
            self.and_label.pack_forget()
            self.value2_entry.pack_forget()
        self.value_entry.configure(state="normal" if cmp in NEEDS_VALUE else "disabled")

    def _set_running(self, active):
        self.next_btn.configure(state="normal" if active else "disabled")
        self.reset_btn.configure(state="normal" if active else "disabled")
        self.first_btn.configure(state="disabled" if active else "normal")
        self.type_box.configure(state="disabled" if active else "readonly")
        self.area.box.configure(state="disabled" if active else "readonly")

    def first_scan(self):
        cmp, vtype = self._cmp(), TYPE_IDS[self.type_box.current()]
        if vtype != "any" and vtype not in values.NUMERIC:
            cmp = "eq"
        elif cmp not in FIRST:
            return self.app.say("A first scan has nothing to compare with yet. Pick 'is exactly' or 'could be anything'.")
        area, lo, hi = self.area.get()
        value, value2, aligned = self.value.get().strip(), self.value2.get().strip(), self.aligned.get()

        def work(progress):
            g, regions = self.app.s.need_game(), self.app.s.regions(area, lo, hi)
            scan = MultiScan(g, regions, aligned) if vtype == "any" else Scan(g, regions, vtype, aligned)
            scan.first(cmp, value, value2, progress)
            return scan

        def done(scan):
            self.scan = scan
            self.history = [(cmp, value, scan.count)]
            self._set_running(True)
            self._show()

        self.app.job("First scan", work, done)

    def next_scan(self):
        if not self.scan:
            return
        cmp, value, value2 = self._cmp(), self.value.get().strip(), self.value2.get().strip()
        if cmp == "unknown":
            return self.app.say("'Could be anything' only makes sense for a first scan.")
        scan = self.scan

        def done(count):
            self.history.append((cmp, value, count))
            self._show()

        self.app.job("Next scan", lambda progress: scan.next(cmp, value, value2, progress), done)

    def reset(self):
        self.scan = None
        self.rows = []
        self.history = []
        self.tree.delete(*self.tree.get_children())
        self._set_running(False)
        self.summary.configure(text=START_HINT, foreground=self.app.pal["dim"])
        self.trail.configure(text="")

    def _step(self, cmp, value):
        label = next(c[0] for c in COMPARES if c[1] == cmp)
        return "%s %s" % (label, value) if cmp in NEEDS_VALUE else label

    def _show(self):
        scan = self.scan
        self.rows = scan.results(0, MAX_ROWS)
        self.tree.delete(*self.tree.get_children())
        for r in self.rows:
            self.tree.insert("", "end", iid=str(r["addr"]), values=(
                hex8(r["addr"]), values.LABELS[r["type"]], r["value"], r["value"], r.get("previous", "")))
        count = scan.count
        noun = "address%s" % ("" if count == 1 else "es")
        last = self.history[-1]
        before = self.history[-2] if len(self.history) > 1 else None
        if before and last[0] == "eq" and before[0] == "eq":
            text = "%s %s went from %s to %s" % (format(count, ","), noun, before[1], last[1])
        elif len(self.history) == 1 and last[0] == "eq":
            text = "%s %s contain%s %s" % (format(count, ","), noun, "s" if count == 1 else "", last[1])
        else:
            text = "%s %s match" % (format(count, ","), noun)
        text += "  (searched %s)" % size_text(scan.total_bytes())
        if count > len(self.rows):
            text += ", showing the first %d" % len(self.rows)
        self.summary.configure(text=text, foreground="")
        self.trail.configure(text="   >   ".join(
            "Scan %d: %s (%s found)" % (i + 1, self._step(c, v), format(n, ",")) for i, (c, v, n) in enumerate(self.history)))
        self.app.say(text)

    def _tick(self):
        if (self.live.get() and self.scan and self.rows and not self.loading and not self.app.busy
                and self.app.visible(self) and self.app.s.running):
            self.loading = True
            scan, rows = self.scan, self.rows[:LIVE_ROWS]

            def work():
                return scan, rows, self.app.s.need_game().read_small([(r["addr"], r["size"] or 16) for r in rows])

            def done(result):
                self.loading = False
                got_scan, got_rows, raws = result
                if got_scan is not self.scan:
                    return
                for r, raw in zip(got_rows, raws):
                    iid = str(r["addr"])
                    if not self.tree.exists(iid):
                        continue
                    now = "not mapped" if raw is None else values.decode(r["type"], raw)
                    self.tree.set(iid, "now", now)
                    self.tree.item(iid, tags=("changed",) if str(now) != str(r["value"]) else ())

            def fail(_):
                self.loading = False

            self.app.tasks.run(work, done, fail)
        self.after(1500, self._tick)

    def _selected(self):
        picked = {int(i) for i in self.tree.selection()}
        return [r for r in self.rows if r["addr"] in picked]

    def view(self):
        rows = self._selected()
        if rows:
            self.app.goto(rows[0]["addr"])

    def add_mod(self):
        rows = self._selected()
        if rows:
            self.app.add_mod(hex8(rows[0]["addr"]), rows[0]["type"])

    def set_value(self):
        rows = self._selected()
        if not rows:
            return self.app.say("Select one or more rows first.")
        kinds = sorted({values.LABELS[r["type"]].lower() for r in rows})
        result = Form(self, "Set value", [("value", "New value", "mono", "", None)],
                      note="Writes to %d selected address%s in the running game (%s)." % (
                          len(rows), "" if len(rows) == 1 else "es", ", ".join(kinds)), ok="Write").wait()
        if not result:
            return
        try:
            writes = [(r["addr"], values.encode(r["type"], result["value"])) for r in rows]
        except ValueError as e:
            return self.app.fail(e)

        def work():
            g = self.app.s.need_game()
            for addr, data in writes:
                g.write(addr, data)
            return len(writes)

        self.app.tasks.run(work, lambda n: self.app.say(
            "Wrote %s to %d address%s" % (result["value"], n, "" if n == 1 else "es")))
