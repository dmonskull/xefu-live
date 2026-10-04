import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import values
from .common import HEADING, MONO, TITLE, Form, hex8, make_tree

TYPE_LABELS = [values.LABELS[t] for t in values.ALL]
ADDRESS_NOTE = ("The address is the one Ghidra shows for the game's XBE (hex). A saved name or a formula "
                "works too: BB85B8 + 2*6140, or [C01234] + 10 to follow a pointer.")


def type_id(label):
    return values.ALL[TYPE_LABELS.index(label)] if label in TYPE_LABELS else "u32"


class ModsTab(ttk.Frame):
    """The table of named addresses and byte patches for the running game."""

    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.data = {"entries": [], "patches": []}
        self.loading = False
        self.shape = None

        row = ttk.Frame(self)
        row.pack(fill="x")
        self.title = ttk.Label(row, text="Mods", font=TITLE)
        self.title.pack(side="left")
        ttk.Button(row, text="Names...", command=self.names).pack(side="right")
        ttk.Button(row, text="Export...", command=self.export).pack(side="right", padx=6)
        ttk.Button(row, text="Import...", command=self.import_).pack(side="right")
        self.file_note = ttk.Label(self, foreground=app.pal["dim"], text="")
        self.file_note.pack(fill="x", pady=(2, 8))

        frame, self.tree = make_tree(self, (
            ("frozen", "Frozen", 60, "center"), ("name", "Name", 250, "w"), ("addr", "Address", 230, "w"),
            ("type", "Type", 130, "w"), ("live", "In the game now", 170, "w"), ("value", "Your value", 150, "w")),
            height=9)
        frame.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._selected_changed())
        self.tree.bind("<Double-1>", lambda e: self.edit())
        self.tree.tag_configure("frozen", foreground=app.pal["ok"])
        self.tree.tag_configure("bad", foreground=app.pal["bad"])

        row = ttk.Frame(self)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Add...", command=self.add).pack(side="left")
        ttk.Button(row, text="Edit...", command=self.edit).pack(side="left", padx=6)
        ttk.Button(row, text="Delete", command=self.delete).pack(side="left")
        ttk.Button(row, text="View in Memory", command=self.view).pack(side="left", padx=6)
        ttk.Separator(row, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(row, text="New value").pack(side="left")
        self.value = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.value, width=16, font=MONO)
        entry.pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: self.set_now())
        ttk.Button(row, text="Set now", command=self.set_now).pack(side="left")
        ttk.Button(row, text="Freeze at this value", command=self.freeze).pack(side="left", padx=6)
        ttk.Button(row, text="Unfreeze", command=self.unfreeze).pack(side="left")

        ttk.Label(self, text="Byte patches", font=HEADING).pack(anchor="w", pady=(16, 0))
        ttk.Label(self, foreground=app.pal["dim"], wraplength=1000, justify="left", text=(
            "A patch swaps bytes at an address and can be switched back. Patches to data act at once. "
            "Patches to code only affect code the game has not run yet, because xefu keeps its own "
            "translated copy of code that already ran.")).pack(anchor="w", pady=(2, 6))
        frame, self.ptree = make_tree(self, (
            ("on", "On", 50, "center"), ("name", "Name", 250, "w"), ("addr", "Address", 160, "w"),
            ("bytes", "Patch bytes", 230, "w"), ("orig", "Original bytes", 230, "w")), height=5)
        frame.pack(fill="x")
        self.ptree.tag_configure("on", foreground=app.pal["ok"])
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Add patch...", command=self.add_patch).pack(side="left")
        ttk.Button(row, text="Turn on", command=lambda: self.toggle(True)).pack(side="left", padx=6)
        ttk.Button(row, text="Turn off", command=lambda: self.toggle(False)).pack(side="left")
        ttk.Button(row, text="Delete patch", command=self.delete_patch).pack(side="left", padx=6)
        self.after(1500, self._tick)

    def on_game(self):
        m = self.app.s.mods
        self.title.configure(text="Mods for %s" % m.title)
        self.file_note.configure(text="Saved automatically in %s" % m.path)
        self.shape = None
        self.refresh()

    def _tick(self):
        if self.app.visible(self) and self.app.s.running and not self.app.busy:
            self.refresh()
        self.after(1500, self._tick)

    def refresh(self):
        if self.loading or not self.app.s.running:
            return
        self.loading = True

        def done(data):
            self.loading = False
            self.data = data
            self._draw()
            if data.get("freeze_error"):
                self.app.say("Freeze problem: %s" % data["freeze_error"])

        def fail(_):
            self.loading = False

        self.app.tasks.run(self.app.s.mods.live, done, fail)

    def _draw(self):
        entries, patches = self.data["entries"], self.data["patches"]
        shape = ([e["id"] for e in entries], [p["id"] for p in patches])
        if shape != self.shape:     # rows were added or removed, rebuild both tables
            keep = self.tree.selection()
            self.tree.delete(*self.tree.get_children())
            self.ptree.delete(*self.ptree.get_children())
            for e in entries:
                self.tree.insert("", "end", iid=str(e["id"]))
            for p in patches:
                self.ptree.insert("", "end", iid=str(p["id"]))
            self.shape = shape
            for iid in keep:
                if self.tree.exists(iid):
                    self.tree.selection_add(iid)
        for e in entries:
            live = e.get("live")
            address = e["address"]
            if "resolved" in e and hex8(e["resolved"]) != address.upper().zfill(8):
                address = "%s  = %s" % (address, hex8(e["resolved"]))
            self.tree.item(str(e["id"]), values=(
                "yes" if e.get("frozen") else "", e["name"], address, values.LABELS[e["type"]],
                e.get("error", "") if live is None else live, e.get("value", "")),
                tags=("bad",) if live is None else ("frozen",) if e.get("frozen") else ())
        for p in patches:
            self.ptree.item(str(p["id"]), values=(
                "on" if p.get("enabled") else "", p["name"], p["address"], p["on"],
                p.get("off", "") or "(read when turned on)"), tags=("on",) if p.get("enabled") else ())

    def _picked(self, tree, items, what):
        sel = tree.selection()
        if not sel:
            self.app.say("Select %s in the list first." % what)
            return None
        return next((x for x in items if str(x["id"]) == sel[0]), None)

    def _entry(self):
        return self._picked(self.tree, self.data["entries"], "an entry")

    def _patch(self):
        return self._picked(self.ptree, self.data["patches"], "a patch")

    def _selected_changed(self):
        sel = self.tree.selection()
        e = next((e for e in self.data["entries"] if sel and str(e["id"]) == sel[0]), None)
        if e:
            self.value.set(e.get("value") or ("" if e.get("live") is None else str(e["live"])))

    def _do(self, fn, message):
        def done(_):
            self.app.say(message)
            self.refresh()
        self.app.tasks.run(fn, done)

    def _form(self, title, e, ok):
        return Form(self, title, [
            ("name", "Name", "text", e.get("name", ""), None),
            ("address", "Address", "mono", e.get("address", ""), None),
            ("type", "Type", "choice", values.LABELS[e.get("type", "float")], TYPE_LABELS),
            ("value", "Value to set", "mono", e.get("value", ""), None),
            ("note", "Note", "text", e.get("note", ""), None),
        ], note=ADDRESS_NOTE, ok=ok).wait()

    def add(self, address="", vtype="float"):
        r = self._form("Add a mod entry", {"address": address, "type": vtype}, "Add")
        if not r or not r["address"]:
            return
        mods = self.app.s.mods
        self._do(lambda: mods.add_entry(r["name"], r["address"], type_id(r["type"]), r["value"], r["note"]),
                 "Added %s" % (r["name"] or r["address"]))

    def edit(self):
        e = self._entry()
        r = self._form("Edit entry", e, "Save") if e else None
        if not r:
            return
        mods = self.app.s.mods
        self._do(lambda: mods.update_entry(e["id"], name=r["name"], address=r["address"], type=type_id(r["type"]),
                                           value=r["value"], note=r["note"]), "Saved %s" % r["name"])

    def delete(self):
        e = self._entry()
        if e and messagebox.askyesno("Delete entry", "Delete '%s' from the mod table?" % e["name"], parent=self):
            mods = self.app.s.mods
            self._do(lambda: mods.delete("entry", e["id"]), "Deleted %s" % e["name"])

    def view(self):
        e = self._entry()
        if e and "resolved" in e:
            self.app.goto(e["resolved"])

    def set_now(self):
        e = self._entry()
        if e:
            value, mods = self.value.get().strip(), self.app.s.mods
            self._do(lambda: mods.set_value(e["id"], value), "Set %s to %s" % (e["name"], value))

    def freeze(self):
        e = self._entry()
        if not e:
            return
        value, mods = self.value.get().strip(), self.app.s.mods

        def work():
            mods.set_value(e["id"], value)
            mods.update_entry(e["id"], frozen=True)

        self._do(work, "%s is frozen at %s" % (e["name"], value))

    def unfreeze(self):
        e = self._entry()
        if e:
            mods = self.app.s.mods
            self._do(lambda: mods.update_entry(e["id"], frozen=False), "%s is no longer frozen" % e["name"])

    def add_patch(self):
        r = Form(self, "Add a byte patch", [
            ("name", "Name", "text", "", None),
            ("address", "Address", "mono", "", None),
            ("on", "New bytes (hex)", "mono", "", None),
            ("off", "Original bytes (optional)", "mono", "", None),
        ], note="Leave the original bytes empty and they are read from the game the first time the patch is turned on.",
            ok="Add").wait()
        if not r or not r["address"] or not r["on"]:
            return
        mods = self.app.s.mods
        self._do(lambda: mods.add_patch(r["name"], r["address"], r["on"], r["off"]), "Added patch %s" % r["name"])

    def toggle(self, enable):
        p = self._patch()
        if p:
            mods = self.app.s.mods
            self._do(lambda: mods.toggle_patch(p["id"], enable), "%s turned %s" % (p["name"], "on" if enable else "off"))

    def delete_patch(self):
        p = self._patch()
        if p and messagebox.askyesno("Delete patch", "Delete the patch '%s'? This does not undo it in the game." % p["name"],
                                     parent=self):
            mods = self.app.s.mods
            self._do(lambda: mods.delete("patch", p["id"]), "Deleted patch %s" % p["name"])

    def export(self):
        mods = self.app.s.mods
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".json",
                                            initialfile="%s %s mods.json" % (mods.title_id, mods.title))
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(mods.export(), f, indent=2)
            self.app.say("Exported to %s" % path)

    def import_(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("Mod tables", "*.json")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            return self.app.fail(e)
        mods = self.app.s.mods
        if data.get("title_id") and data["title_id"] != mods.title_id:
            if not messagebox.askyesno("Different game", "That table was made for %s (%s), not the game that is "
                                       "running. Import anyway?" % (data.get("title", "another game"), data["title_id"]),
                                       parent=self):
                return
        self._do(lambda: mods.import_data(data), "Imported %s" % path)

    def names(self):
        mods = self.app.s.mods
        win = tk.Toplevel(self)
        win.title("Names")
        win.transient(self.winfo_toplevel())
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, wraplength=460, justify="left", text=(
            "One per line: a name, then its address in hex. Names can be used anywhere an address is "
            "asked for, for example players + 2*6140.")).pack(anchor="w")
        text = tk.Text(frame, width=60, height=14, font=MONO)
        text.pack(fill="both", expand=True, pady=8)
        text.insert("1.0", mods.symbols_text())

        def save():
            try:
                mods.set_symbols(text.get("1.0", "end"))
            except ValueError as e:
                return self.app.fail("Could not read that list: %s" % e)
            win.destroy()
            self.app.say("Saved %d names" % len(mods.symbols))

        row = ttk.Frame(frame)
        row.pack(anchor="e")
        ttk.Button(row, text="Cancel", command=win.destroy).pack(side="left", padx=4)
        ttk.Button(row, text="Save", command=save).pack(side="left")
