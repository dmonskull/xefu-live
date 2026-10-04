"""Memory search: a first scan over an area, then next scans that narrow the hits down."""
import re

import numpy as np

from . import values

FIRST = ("eq", "ne", "gt", "lt", "between", "unknown")
NEXT = ("eq", "ne", "gt", "lt", "between", "changed", "unchanged", "increased", "decreased", "incby", "decby")


def reread(guest, regions, old_snap, candidates, progress=None):
    """Read the candidates again. candidates = [(offsets per region, value size), ...]

    When only a few pages still hold candidates just those pages are read.
    """
    page_sets = []
    for i, (va, _) in enumerate(regions):
        parts = [np.concatenate([(va + offs[i]) >> 12, (va + offs[i] + size - 1) >> 12])
                 for offs, size in candidates if len(offs[i])]
        page_sets.append(np.unique(np.concatenate(parts)) if parts else np.empty(0, dtype=np.int64))
    if sum(len(p) for p in page_sets) * 0x1000 > sum(size for _, size in regions) // 4:
        return guest.read_ranges(regions, progress)
    ranges, where = [], []
    for i, pages in enumerate(page_sets):
        if not len(pages):
            continue
        breaks = np.nonzero(np.diff(pages) > 1)[0]
        for s, e in zip(np.concatenate([[0], breaks + 1]), np.concatenate([breaks, [len(pages) - 1]])):
            ranges.append((int(pages[s]) << 12, (int(pages[e]) - int(pages[s]) + 1) << 12))
            where.append(i)
    got = guest.read_ranges(ranges, progress) if ranges else []
    snap = [bytearray(buf) for buf in old_snap]
    for (start, size), i, data in zip(ranges, where, got):
        va, length = regions[i]
        a, b = max(start, va), min(start + size, va + length)
        snap[i][a - va:b - va] = data[a - start:b - start]
    return [bytes(buf) for buf in snap]


class Scan:
    """Search for one value type. Keeps the last two reads so scans can compare against them."""

    def __init__(self, guest, regions, vtype, aligned=True):
        if vtype not in values.ALL:
            raise ValueError("unknown type %r" % vtype)
        self.guest = guest
        self.regions = [(va, size) for va, size in regions if size > 0]
        if not self.regions:
            raise ValueError("there is no memory in that area to search")
        self.vtype = vtype
        self.numeric = vtype in values.NUMERIC
        self.size = values.NUMERIC[vtype][1] if self.numeric else 0
        self.align = min(self.size, 4) if aligned and self.numeric else 1
        if self.numeric and not aligned and self.size > 4:
            raise ValueError("unaligned search is limited to values of 4 bytes or less")
        self.snap = None
        self.prev_snap = None
        self.offs = None        # candidate offsets, one array per region
        self.scans = 0
        self.pattern = None

    @property
    def count(self):
        return 0 if self.offs is None else int(sum(len(o) for o in self.offs))

    def total_bytes(self):
        return sum(size for _, size in self.regions)

    def _all_offsets(self, va, length):
        start = (-va) % self.align
        n = (length - start - self.size) // self.align + 1
        return start + np.arange(max(n, 0), dtype=np.int64) * self.align

    def _values(self, buf, offs, raw=False):
        dt = np.dtype("<u%d" % self.size) if raw else values.dtype(self.vtype)
        n = len(offs)
        if n == 0:
            return np.empty(0, dtype=dt)
        first = int(offs[0])
        if self.size == self.align and int(offs[-1]) - first == (n - 1) * self.size:
            return np.frombuffer(buf, dtype=dt, count=n, offset=first)     # one unbroken run, no copy
        u8 = np.frombuffer(buf, dtype=np.uint8)
        steps = np.arange(self.size, dtype=np.int64)
        out = np.empty(n, dtype=dt)
        for i in range(0, n, 1 << 20):
            part = offs[i:i + (1 << 20)]
            out[i:i + len(part)] = np.ascontiguousarray(u8[part[:, None] + steps]).view(dt).ravel()
        return out

    def _test(self, new, old, new_raw, old_raw, cmp, a, b, tol):
        if cmp == "unknown":
            return np.ones(len(new), dtype=bool)
        if cmp == "changed":
            return new_raw != old_raw
        if cmp == "unchanged":
            return new_raw == old_raw
        flt = values.is_float(self.vtype)
        with np.errstate(invalid="ignore", over="ignore"):
            if flt:
                new = new.astype(np.float64)
                old = old.astype(np.float64) if old is not None else None
            elif cmp in ("incby", "decby", "increased", "decreased") and self.size < 8:
                new, old = new.astype(np.int64), old.astype(np.int64)
            if cmp == "eq":
                return np.abs(new - a) <= tol if flt else new == a
            if cmp == "ne":
                return ~(np.abs(new - a) <= tol) if flt else new != a
            if cmp == "gt":
                return new > a
            if cmp == "lt":
                return new < a
            if cmp == "between":
                return (new >= min(a, b)) & (new <= max(a, b))
            if cmp == "increased":
                return new > old
            if cmp == "decreased":
                return new < old
            if cmp == "incby":
                return np.abs((new - old) - a) <= tol if flt else (new - old) == a
            if cmp == "decby":
                return np.abs((old - new) - a) <= tol if flt else (old - new) == a
        raise ValueError("unknown comparison %r" % cmp)

    def _args(self, cmp, value, value2):
        a = b = None
        tol = 0
        if cmp in ("eq", "ne", "gt", "lt", "between", "incby", "decby"):
            if value in (None, ""):
                raise ValueError("type a value to search for")
            a = values.parse(self.vtype, value)
            tol = values.tolerance(self.vtype, value)
        if cmp == "between":
            if value2 in (None, ""):
                raise ValueError("type the second value")
            b = values.parse(self.vtype, value2)
        return a, b, tol

    def first(self, cmp, value=None, value2=None, progress=None, snap=None):
        if not self.numeric:
            return self._first_pattern(value, progress)
        if cmp not in FIRST:
            raise ValueError("a first scan cannot use %r" % cmp)
        a, b, tol = self._args(cmp, value, value2)
        if snap is None:
            snap = self.guest.read_ranges(self.regions, progress)
        offs = []
        for (va, _), buf in zip(self.regions, snap):
            cand = self._all_offsets(va, len(buf))
            if cmp != "unknown" and len(cand):
                cand = cand[self._test(self._values(buf, cand), None, None, None, cmp, a, b, tol)]
            offs.append(cand)
        self.snap, self.offs, self.scans = snap, offs, 1
        return self.count

    def _first_pattern(self, value, progress):
        if self.vtype == "bytes":
            data, mask = values.parse_pattern(value)
        else:
            data = values.encode(self.vtype, value)
            mask = [True] * len(data)
        if not data:
            raise ValueError("type something to search for")
        rx = re.compile(b"".join(re.escape(bytes([c])) if m else b"." for c, m in zip(data, mask)), re.DOTALL)
        self.pattern = (data, mask)
        self.size = len(data)
        snap = self.guest.read_ranges(self.regions, progress)
        offs = []
        for buf in snap:
            found, pos = [], 0
            while True:
                m = rx.search(buf, pos)
                if not m:
                    break
                found.append(m.start())
                pos = m.start() + 1
            offs.append(np.array(found, dtype=np.int64))
        self.snap, self.offs, self.scans = snap, offs, 1
        return self.count

    def next(self, cmp, value=None, value2=None, progress=None, snap=None):
        if self.offs is None:
            raise ValueError("run a first scan before a next scan")
        if not self.numeric:
            if cmp not in ("eq", "changed", "unchanged"):
                raise ValueError("text and byte searches only support: is exactly, changed, did not change")
        elif cmp not in NEXT:
            raise ValueError("unknown comparison %r" % cmp)
        a, b, tol = self._args(cmp, value, value2) if self.numeric else (None, None, 0)
        if snap is None:
            snap = reread(self.guest, self.regions, self.snap, [(self.offs, self.size)], progress)
        offs = []
        for buf, old_buf, cand in zip(snap, self.snap, self.offs):
            if not len(cand):
                offs.append(cand)
                continue
            if self.numeric:
                keep = self._test(self._values(buf, cand), self._values(old_buf, cand),
                                  self._values(buf, cand, raw=True), self._values(old_buf, cand, raw=True),
                                  cmp, a, b, tol)
            else:
                data, mask = self.pattern
                new = np.frombuffer(buf, np.uint8)[cand[:, None] + np.arange(self.size)]
                old = np.frombuffer(old_buf, np.uint8)[cand[:, None] + np.arange(self.size)]
                same = (new == old).all(axis=1)
                if cmp == "eq":
                    keep = ((new == np.frombuffer(data, np.uint8)) | ~np.array(mask)).all(axis=1)
                else:
                    keep = same if cmp == "unchanged" else ~same
            offs.append(cand[keep])
        self.prev_snap = self.snap
        self.snap, self.offs = snap, offs
        self.scans += 1
        return self.count

    def results(self, start=0, limit=200):
        out, skipped = [], 0
        for i, ((va, _), buf, cand) in enumerate(zip(self.regions, self.snap, self.offs)):
            if skipped + len(cand) <= start:
                skipped += len(cand)
                continue
            first = max(0, start - skipped)
            for off in cand[first:first + limit - len(out)].tolist():
                row = {"addr": va + off, "type": self.vtype, "size": self.size,
                       "value": values.decode(self.vtype, buf[off:off + self.size])}
                if self.prev_snap is not None:
                    row["previous"] = values.decode(self.vtype, self.prev_snap[i][off:off + self.size])
                out.append(row)
            skipped += len(cand)
            if len(out) >= limit:
                break
        return out


# also the order used to label an address that matches as more than one type
ANY_TYPES = ("u32", "u16", "u8", "float", "double")


class MultiScan:
    """Search for a number without knowing how the game stores it.

    Runs the same search as byte, 2 bytes, 4 bytes, float and double over one read of memory.
    """

    vtype = "any"
    size = 0

    def __init__(self, guest, regions, aligned=True):
        self.guest = guest
        self.subs = [Scan(guest, regions, t, aligned or t == "double") for t in ANY_TYPES]
        self.regions = self.subs[0].regions
        self.scans = 0
        self.hits = None        # offsets that matched as any type, one array per region

    def total_bytes(self):
        return sum(size for _, size in self.regions)

    @property
    def count(self):
        return 0 if self.hits is None else int(sum(len(h) for h in self.hits))

    def _run(self, method, cmp, value, value2, snap):
        ran = 0
        for sub in self.subs:
            try:
                getattr(sub, method)(cmp, value, value2, None, snap)
                ran += 1
            except ValueError:
                # the value doesn't fit this type (300 in a byte, 1.5 in an int): nothing matches there
                sub.prev_snap, sub.snap = sub.snap, snap
                sub.offs = [np.empty(0, dtype=np.int64) for _ in self.regions]
                sub.scans += 1
        if not ran:
            raise ValueError("%r is not a number" % value)
        self.hits = []
        for i, buf in enumerate(snap):
            mask = np.zeros(len(buf), dtype=bool)
            for sub in self.subs:
                mask[sub.offs[i]] = True
            self.hits.append(np.flatnonzero(mask))

    def first(self, cmp, value=None, value2=None, progress=None):
        if cmp == "unknown":
            raise ValueError("pick one type (for example Float or 4 bytes) to search for an unknown value")
        if cmp not in FIRST:
            raise ValueError("a first scan cannot use %r" % cmp)
        if value in (None, ""):
            raise ValueError("type a value to search for")
        self._run("first", cmp, value, value2, self.guest.read_ranges(self.regions, progress))
        self.scans = 1
        return self.count

    def next(self, cmp, value=None, value2=None, progress=None):
        if self.hits is None:
            raise ValueError("run a first scan before a next scan")
        if cmp not in NEXT:
            raise ValueError("unknown comparison %r" % cmp)
        snap = reread(self.guest, self.regions, self.subs[0].snap,
                      [(sub.offs, sub.size) for sub in self.subs], progress)
        self._run("next", cmp, value, value2, snap)
        self.scans += 1
        return self.count

    def results(self, start=0, limit=200):
        out, skipped = [], 0
        for i, ((va, _), offs) in enumerate(zip(self.regions, self.hits)):
            if skipped + len(offs) <= start:
                skipped += len(offs)
                continue
            first = max(0, start - skipped)
            for off in offs[first:first + limit - len(out)].tolist():
                for sub in self.subs:
                    cand = sub.offs[i]
                    k = int(np.searchsorted(cand, off))
                    if k < len(cand) and int(cand[k]) == off:
                        row = {"addr": va + off, "type": sub.vtype, "size": sub.size,
                               "value": values.decode(sub.vtype, sub.snap[i][off:off + sub.size])}
                        if sub.prev_snap is not None:
                            row["previous"] = values.decode(sub.vtype, sub.prev_snap[i][off:off + sub.size])
                        out.append(row)
                        break
            skipped += len(offs)
            if len(out) >= limit:
                break
        return out
