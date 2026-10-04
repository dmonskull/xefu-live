"""Mod tables: named addresses and byte patches for one game, saved as a JSON file per title."""
import json
import os
import re
import threading
import time

from . import paths, values

FREEZE_INTERVAL = 0.2


class ModTable:
    def __init__(self, guest):
        self.guest = guest
        self.title_id = None
        self.title = ""
        self.entries = []
        self.patches = []
        self.symbols = {}
        self.path = None
        self.freeze_error = ""
        self._lock = threading.RLock()
        self._next_id = 1
        self._thread = None
        self._stop = threading.Event()

    def load_for(self, title_id, title):
        with self._lock:
            self.title_id, self.title = title_id, title
            folder = paths.path("mods")
            os.makedirs(folder, exist_ok=True)
            name = "%s %s.json" % (title_id, re.sub(r"[^A-Za-z0-9 _.-]+", "", title).strip() or "game")
            self.path = os.path.join(folder, name)
            self.entries, self.patches, self.symbols = [], [], {}
            # the user's own table wins, otherwise start from a table shipped with the app
            for folder in (folder, paths.bundled_tables()):
                found = [f for f in os.listdir(folder) if f.upper().startswith(title_id.upper()) and f.endswith(".json")] \
                    if os.path.isdir(folder) else []
                if found:
                    with open(os.path.join(folder, found[0]), encoding="utf-8") as f:
                        self._apply(json.load(f))
                    break
            self.guest.symbols = self.symbols

    def _apply(self, data):
        self.entries = [dict(e) for e in data.get("entries", [])]
        self.patches = [dict(p) for p in data.get("patches", [])]
        self.symbols = dict(data.get("symbols", {}))
        self._next_id = 1
        for entry in self.entries:
            entry["id"] = self._next_id
            entry["frozen"] = False
            self._next_id += 1
        for patch in self.patches:
            patch["id"] = self._next_id
            patch["enabled"] = False
            self._next_id += 1

    def export(self):
        with self._lock:
            return {
                "title_id": self.title_id,
                "title": self.title,
                "entries": [{k: e.get(k, "") for k in ("name", "address", "type", "value", "note")} for e in self.entries],
                "patches": [{k: p.get(k, "") for k in ("name", "address", "on", "off", "note")} for p in self.patches],
                "symbols": self.symbols,
            }

    def save(self):
        with self._lock:
            if not self.path:
                return
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.export(), f, indent=2)
            os.replace(tmp, self.path)

    def import_data(self, data):
        with self._lock:
            for e in data.get("entries", []):
                self.add_entry(e.get("name", ""), e.get("address", ""), e.get("type", "u32"),
                               e.get("value", ""), e.get("note", ""), save=False)
            for p in data.get("patches", []):
                self.add_patch(p.get("name", ""), p.get("address", ""), p.get("on", ""),
                               p.get("off", ""), p.get("note", ""), save=False)
            self.symbols.update(data.get("symbols", {}))
            self.guest.symbols = self.symbols
            self.save()

    def _find(self, items, item_id):
        for item in items:
            if item["id"] == item_id:
                return item
        raise KeyError("that entry no longer exists")

    def add_entry(self, name, address, vtype, value="", note="", save=True):
        if vtype not in values.ALL:
            raise ValueError("unknown type %r" % vtype)
        if "[" not in str(address):
            self.guest.resolve(address)     # catch typos now instead of on every refresh
        with self._lock:
            entry = {"id": self._next_id, "name": name or "Unnamed", "address": str(address), "type": vtype,
                     "value": str(value), "note": note, "frozen": False}
            self._next_id += 1
            self.entries.append(entry)
            if save:
                self.save()
            return entry

    def update_entry(self, item_id, **fields):
        with self._lock:
            entry = self._find(self.entries, item_id)
            for k in ("name", "address", "type", "value", "note"):
                if fields.get(k) is not None:
                    entry[k] = str(fields[k])
            if fields.get("frozen") is not None:
                entry["frozen"] = bool(fields["frozen"])
            self.save()
            self._start_freezer()
            return entry

    def delete(self, kind, item_id):
        with self._lock:
            items = self.entries if kind == "entry" else self.patches
            items.remove(self._find(items, item_id))
            self.save()

    def set_value(self, item_id, value):
        with self._lock:
            entry = self._find(self.entries, item_id)
            data = values.encode(entry["type"], value)
            if entry["type"] == "text":
                data += b"\0"
            elif entry["type"] == "text16":
                data += b"\0\0"
            entry["value"] = str(value)
        self.guest.write(self.guest.resolve(entry["address"]), data)
        self.save()

    def live(self):
        """Entries and patches with what is in the game right now."""
        with self._lock:
            entries = [dict(e) for e in self.entries]
            patches = [dict(p) for p in self.patches]
        wanted, owners = [], []
        for e in entries:
            try:
                e["resolved"] = self.guest.resolve(e["address"])
                wanted.append((e["resolved"], values.size_of(e["type"]) if e["type"] in values.NUMERIC else 32))
                owners.append(e)
            except Exception as err:
                e["live"] = None
                e["error"] = str(err)
        for e, raw in zip(owners, self.guest.read_small(wanted) if wanted else []):
            if raw is None:
                e["live"] = None
                e["error"] = "not mapped right now"
            else:
                e["live"] = values.decode(e["type"], raw)
        for p in patches:
            try:
                addr = self.guest.resolve(p["address"])
                on = values.encode("bytes", p["on"])
                p["resolved"] = addr
                p["enabled"] = self.guest.read(addr, len(on)) == on
            except Exception as err:
                p["error"] = str(err)
        return {"entries": entries, "patches": patches, "freeze_error": self.freeze_error}

    def symbols_text(self):
        return "\n".join("%s %s" % (k, v) for k, v in self.symbols.items())

    def set_symbols(self, text):
        symbols = {}
        for line in text.splitlines():
            parts = line.replace(",", " ").replace("=", " ").split()
            if len(parts) >= 2 and not line.lstrip().startswith("#"):
                int(parts[1], 16)
                symbols[parts[0]] = parts[1]
        with self._lock:
            self.symbols = symbols
            self.guest.symbols = symbols
            self.save()

    def add_patch(self, name, address, on, off="", note="", save=True):
        if off and len(values.encode("bytes", off)) != len(values.encode("bytes", on)):
            raise ValueError("the original bytes must be the same length as the patch bytes")
        values.encode("bytes", on)
        with self._lock:
            patch = {"id": self._next_id, "name": name or "Unnamed patch", "address": str(address),
                     "on": on, "off": off, "note": note, "enabled": False}
            self._next_id += 1
            self.patches.append(patch)
            if save:
                self.save()
            return patch

    def toggle_patch(self, item_id, enable):
        with self._lock:
            patch = self._find(self.patches, item_id)
        addr = self.guest.resolve(patch["address"])
        on = values.encode("bytes", patch["on"])
        if enable:
            now = self.guest.read(addr, len(on))
            if not patch.get("off") and now != on:
                patch["off"] = now.hex(" ").upper()     # remember what was there so it can be undone
            self.guest.write(addr, on)
        else:
            if not patch.get("off"):
                raise ValueError("the original bytes are not known, so this patch cannot be undone here")
            self.guest.write(addr, values.encode("bytes", patch["off"]))
        patch["enabled"] = bool(enable)
        self.save()

    def _start_freezer(self):
        if self._thread and self._thread.is_alive():
            return
        if any(e.get("frozen") for e in self.entries):
            self._stop.clear()
            self._thread = threading.Thread(target=self._freeze_loop, daemon=True)
            self._thread.start()

    def _freeze_loop(self):
        while not self._stop.is_set():
            with self._lock:
                frozen = [dict(e) for e in self.entries if e.get("frozen")]
            if not frozen:
                return
            for e in frozen:
                try:
                    self.guest.write(self.guest.resolve(e["address"]), values.encode(e["type"], e["value"]))
                    self.freeze_error = ""
                except Exception as err:
                    self.freeze_error = "%s: %s" % (e["name"], err)
            time.sleep(FREEZE_INTERVAL)

    def unfreeze_all(self):
        with self._lock:
            for e in self.entries:
                e["frozen"] = False
        self._stop.set()
