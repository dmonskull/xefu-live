"""Snapshot an area of memory, then list what is different later."""
import struct
import time

import numpy as np

from . import values


class Snapshot:
    def __init__(self, guest, regions):
        self.guest = guest
        self.regions = [(va, size) for va, size in regions if size > 0]
        if not self.regions:
            raise ValueError("there is no memory in that area")
        self.first = None
        self.last = None
        self.ignore = None      # bytes we were told to stop reporting (timers and such)
        self.taken_at = None

    def total_bytes(self):
        return sum(size for _, size in self.regions)

    def take(self, progress=None):
        self.first = self.guest.read_ranges(self.regions, progress)
        self.last = self.first
        self.ignore = [np.zeros(len(b), dtype=bool) for b in self.first]
        self.taken_at = time.time()

    def diff(self, against="first", limit=500, progress=None):
        if self.first is None:
            raise ValueError("take a first snapshot before checking for changes")
        new = self.guest.read_ranges(self.regions, progress)
        base = self.first if against == "first" else self.last
        rows, changed_bytes, changes = [], 0, 0
        for (va, _), n, o, ig in zip(self.regions, new, base, self.ignore):
            idx = np.flatnonzero((np.frombuffer(n, np.uint8) != np.frombuffer(o, np.uint8)) & ~ig)
            changed_bytes += len(idx)
            if not len(idx):
                continue
            # group by 4 byte word so a changed int or float shows up as one row
            words = np.unique((va + idx) >> 2)
            breaks = np.flatnonzero(np.diff(words) > 1)
            starts = np.concatenate([[0], breaks + 1])
            ends = np.concatenate([breaks, [len(words) - 1]])
            changes += len(starts)
            for s, e in zip(starts.tolist(), ends.tolist()):
                if len(rows) >= limit:
                    break
                a = max((int(words[s]) << 2) - va, 0)
                b = min(((int(words[e]) + 1) << 2) - va, len(n))
                rows.append(self._row(va + a, o[a:b], n[a:b]))
        self.last = new
        return {"changed_bytes": changed_bytes, "changes": changes, "rows": rows,
                "ignored_bytes": int(sum(int(i.sum()) for i in self.ignore))}

    @staticmethod
    def _row(addr, old, new):
        row = {"addr": addr, "size": len(new), "old": old[:32].hex(" ").upper(), "new": new[:32].hex(" ").upper()}
        if len(new) == 4:
            row["as_int"] = [struct.unpack("<I", old)[0], struct.unpack("<I", new)[0]]
            floats = [struct.unpack("<f", old)[0], struct.unpack("<f", new)[0]]
            if all(v == v and (v == 0 or 1e-4 <= abs(v) < 1e9) for v in floats):
                row["as_float"] = [values.fmt_float(v) for v in floats]
        return row

    def ignore_changes(self, progress=None):
        """Stop reporting bytes that are changing on their own right now."""
        if self.first is None:
            raise ValueError("take a first snapshot first")
        new = self.guest.read_ranges(self.regions, progress)
        added = 0
        for n, o, f, ig in zip(new, self.last, self.first, self.ignore):
            cur = np.frombuffer(n, np.uint8)
            noisy = (cur != np.frombuffer(o, np.uint8)) | (cur != np.frombuffer(f, np.uint8))
            added += int((noisy & ~ig).sum())
            ig |= noisy
        self.last = new
        return {"ignored_now": added, "ignored_bytes": int(sum(int(i.sum()) for i in self.ignore))}
