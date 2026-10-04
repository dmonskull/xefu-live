"""The original Xbox game running inside xefu, the 360's Xbox emulator.

xefu gives the emulated Xbox its 64 MB of RAM as one block of 360 memory and
boots a real x86 Xbox kernel in it. So game addresses go through normal x86
page tables stored in that RAM (page directory at physical 0xF000), and the
bytes are little endian exactly as the game sees them.
"""
import re
import struct
import threading
import time

from .xbdm import Unreadable, XbdmError

RAM_SIZE = 0x04000000
PAGE_DIR = 0x0000F000
XBE_BASE = 0x00010000
EMU_BASE = 0x82000000

# (PE timestamp, entry point) of each emulator build
XEFU_BUILDS = {
    (0x437ACD68, 0x000B4328): "xefu",
    (0x4537DDE5, 0x000B4570): "xefu1_1",
    (0x43E94E5E, 0x000B51A0): "xefu2",
    (0x442C87BD, 0x000AF3F8): "xefu3",
    (0x44F633D3, 0x000AF058): "xefu5",
    (0x457DD568, 0x000C37D0): "xefu6",
    (0x474B3577, 0x000C3DA0): "xefu7",
    (0x474B3577, 0x000C1C48): "xefu7b",
}
# global that holds the guest RAM pointer, where known
RAM_BASE_GLOBAL = {"xefu7": 0x821DE210}


class NotRunning(Exception):
    pass


class Unmapped(Exception):
    pass


class Guest:
    TABLE_TTL = 3.0

    def __init__(self, console):
        self.console = console
        self.ram_base = None
        self.emulator = None
        self.xbe = None
        self.symbols = {}
        self._pd = None
        self._pt = {}
        self._tables_at = 0.0
        self._lock = threading.RLock()

    def detect(self):
        with self._lock:
            self.ram_base = self.emulator = self.xbe = self._pd = None
            try:
                head = self.console.read(EMU_BASE, 0x400)
            except (Unreadable, XbdmError):
                raise NotRunning("no title is loaded")
            if head[:2] != b"MZ":
                raise NotRunning("the running title is not the Xbox emulator")
            pe = struct.unpack_from("<I", head, 0x3C)[0]
            stamp = struct.unpack_from("<I", head, pe + 8)[0]
            entry = struct.unpack_from("<I", head, pe + 0x28)[0]
            self.emulator = XEFU_BUILDS.get((stamp, entry))
            if not self.emulator:
                raise NotRunning("the running title is not the Xbox emulator")
            self.ram_base = self._find_ram()
            if self.ram_base is None:
                raise NotRunning("%s is running but the game's memory was not found yet" % self.emulator)
            self.refresh_tables(force=True)
            self.xbe = self._read_xbe()

    def _is_ram(self, base):
        # the emulator's xbox kernel sits at physical 0x10000 and the page directory maps itself
        try:
            if self.console.read(base + 0x10000, 2) != b"MZ":
                return False
            pde = struct.unpack("<I", self.console.read(base + PAGE_DIR + 0x300 * 4, 4))[0]
            return (pde & 0xFFFFF001) == (PAGE_DIR | 1)
        except (Unreadable, XbdmError):
            return False

    def _find_ram(self):
        known = RAM_BASE_GLOBAL.get(self.emulator)
        if known:
            try:
                base = struct.unpack(">I", self.console.read(known, 4))[0]
                if base and self._is_ram(base):
                    return base
            except (Unreadable, XbdmError):
                pass
        # other builds: look at every 16 MB step of the 360's physical memory window
        regions = self.console.regions()
        for base in range(0xC0000000, 0xE0000000, 0x01000000):
            if any(lo <= base and base + RAM_SIZE <= lo + size for lo, size in regions) and self._is_ram(base):
                return base
        return None

    def refresh_tables(self, force=False):
        with self._lock:
            if not force and self._pd is not None and time.time() - self._tables_at < self.TABLE_TTL:
                return
            if self.ram_base is None:
                raise NotRunning("no game detected")
            pd = struct.unpack("<1024I", self.console.read(self.ram_base + PAGE_DIR, 0x1000))
            tables = sorted({e & 0xFFFFF000 for e in pd if e & 1 and not e & 0x80 and (e & 0xFFFFF000) < RAM_SIZE})
            raw = self.console.read_many([(self.ram_base + t, 0x1000) for t in tables])
            self._pt = {t: struct.unpack("<1024I", r) for t, r in zip(tables, raw) if r is not None}
            self._pd = pd
            self._tables_at = time.time()

    def translate(self, va):
        """Game address -> Xbox physical address (None if not mapped)."""
        if self._pd is None:
            self.refresh_tables()
        pde = self._pd[(va >> 22) & 0x3FF]
        if not pde & 1:
            return None
        if pde & 0x80:      # 4 MB page
            phys = (pde & 0xFFC00000) | (va & 0x3FFFFF)
        else:
            table = self._pt.get(pde & 0xFFFFF000)
            if table is None:
                return None
            pte = table[(va >> 12) & 0x3FF]
            if not pte & 1:
                return None
            phys = (pte & 0xFFFFF000) | (va & 0xFFF)
        return phys if phys < RAM_SIZE else None

    def host(self, va):
        """Game address -> 360 address (None if not mapped)."""
        phys = self.translate(va)
        return None if phys is None else self.ram_base + phys

    def spans(self, va, size):
        """Split a game range into [va, 360 address or None, length] runs."""
        out = []
        end = va + size
        while va < end:
            n = min(0x1000 - (va & 0xFFF), end - va)
            h = self.host(va)
            last = out[-1] if out else None
            if last and ((h is None and last[1] is None) or
                         (h is not None and last[1] is not None and last[1] + last[2] == h)):
                last[2] += n
            else:
                out.append([va, h, n])
            va += n
        return out

    def mapped(self, lo=0x00010000, hi=0x80000000):
        self.refresh_tables()
        out = []
        va = lo & ~0xFFF
        while va < hi:
            pde = self._pd[va >> 22]
            if not pde & 1:
                va = ((va >> 22) + 1) << 22
                continue
            step = 0x400000 - (va & 0x3FFFFF) if pde & 0x80 else 0x1000
            if self.translate(va) is not None:
                if out and out[-1][1] == va:
                    out[-1][1] = va + step
                else:
                    out.append([va, va + step])
            va += step
        return [(a, min(b, hi)) for a, b in out]

    def read(self, va, size, fill=None):
        """Unmapped parts raise Unmapped, or are filled with `fill` if given."""
        self.refresh_tables()
        parts = self.spans(va, size)
        if fill is None and any(h is None for _, h, _ in parts):
            raise Unmapped("game address %08X is not mapped" % next(v for v, h, _ in parts if h is None))
        out = bytearray()
        for _, h, n in parts:
            out += fill * n if h is None else self.console.read(h, n)
        return bytes(out)

    def read_ranges(self, ranges, progress=None):
        """Big parallel read of [(va, size), ...]. Unmapped pages read as zeros."""
        self.refresh_tables(force=True)
        spans, layout = [], []
        for va, size in ranges:
            pieces = self.spans(va, size)
            layout.append(pieces)
            spans += [(h, n) for _, h, n in pieces if h is not None]
        data = iter(self.console.read_many(spans, progress))
        out = []
        for pieces in layout:
            buf = bytearray()
            for _, h, n in pieces:
                buf += bytes(n) if h is None else (next(data) or bytes(n))
            out.append(bytes(buf))
        return out

    def read_small(self, items):
        """Many small reads at once: [(va, size), ...] -> [bytes or None, ...]."""
        self.refresh_tables()
        out = [None] * len(items)
        spans, where = [], []
        for i, (va, size) in enumerate(items):
            parts = self.spans(va, size)
            if len(parts) == 1 and parts[0][1] is not None:
                spans.append((parts[0][1], size))
                where.append(i)
            elif all(h is not None for _, h, _ in parts):
                try:
                    out[i] = self.read(va, size)
                except (Unmapped, Unreadable, XbdmError):
                    pass
        for i, data in zip(where, self.console.read_many(spans)):
            out[i] = data
        return out

    def write(self, va, data):
        # page tables can change under us, so don't write through an old lookup
        self.refresh_tables(force=time.time() - self._tables_at > 2.0)
        parts = self.spans(va, len(data))
        if any(h is None for _, h, _ in parts):
            raise Unmapped("game address %08X is not mapped, nothing was written" % va)
        off = 0
        for _, h, n in parts:
            self.console.write(h, data[off:off + n])
            off += n

    def read_u32(self, va):
        return struct.unpack("<I", self.read(va, 4))[0]

    def _read_xbe(self):
        try:
            head = self.read(XBE_BASE, 0x1000)
        except (Unmapped, Unreadable, XbdmError):
            return None
        if head[:4] != b"XBEH":
            return None
        base, hdr_size, image_size, _, _, cert, nsec, sec = struct.unpack_from("<8I", head, 0x104)
        if hdr_size > 0x1000:
            head = self.read(base, min(hdr_size, 0x8000), fill=b"\0")

        def at(addr, n):
            off = addr - base
            return head[off:off + n] if 0 <= off and off + n <= len(head) else b""

        cert_raw = at(cert, 0x60)
        title_id = struct.unpack_from("<I", cert_raw, 8)[0] if len(cert_raw) >= 12 else 0
        title = cert_raw[0xC:0xC + 80].decode("utf-16le", "replace").split("\0")[0] if cert_raw else ""
        sections = []
        for i in range(min(nsec, 64)):
            raw = at(sec + i * 0x38, 0x38)
            if len(raw) < 24:
                break
            flags, va, vsize, _, rsize, name_addr = struct.unpack_from("<6I", raw)
            name = at(name_addr, 16).split(b"\0")[0].decode("latin-1")
            sections.append({"name": name, "va": va, "size": vsize, "writable": bool(flags & 1)})
        return {"base": base, "image_size": image_size, "title": title or "Unknown game",
                "title_id": "%08X" % title_id, "sections": sections}

    def section_of(self, va):
        for s in (self.xbe or {}).get("sections", []):
            if s["va"] <= va < s["va"] + s["size"]:
                return s["name"]
        if self.xbe and self.xbe["base"] <= va < self.xbe["base"] + 0x1000:
            return "XBE header"
        if 0x80000000 <= va < 0x84000000:
            return "kernel / contiguous memory"
        return "heap" if va < 0x80000000 else ""

    def regions(self, preset, custom=None):
        x = self.xbe
        image_end = (x["base"] + x["image_size"] + 0xFFF) & ~0xFFF if x else XBE_BASE
        if preset == "data":
            return [(s["va"], s["size"]) for s in x["sections"] if s["writable"] and not s["name"].startswith("$$")] if x else []
        if preset == "heap":
            return [(a, b - a) for a, b in self.mapped(image_end, 0x80000000)]
        if preset == "all":
            return self.regions("data") + self.regions("heap")
        if preset == "image":
            return [(x["base"], image_end - x["base"])] if x else []
        if preset == "custom" and custom:
            lo, hi = custom
            if hi <= lo:
                raise ValueError("the end address must be above the start address")
            return [(lo, hi - lo)]
        raise ValueError("unknown memory area: %r" % preset)

    def resolve(self, expr):
        """Address expression -> number. Hex numbers, saved names, + - *, and [x] to follow a pointer."""
        if isinstance(expr, int):
            return expr
        tokens = re.findall(r"\s*([A-Za-z_][A-Za-z0-9_.:$@?]*|[0-9][0-9A-Fa-fxX]*|[\[\]()+\-*])", expr)
        if "".join(tokens) != re.sub(r"\s+", "", expr):
            raise ValueError("cannot understand the address %r" % expr)
        pos = [0]

        def peek():
            return tokens[pos[0]] if pos[0] < len(tokens) else None

        def take():
            pos[0] += 1
            return tokens[pos[0] - 1]

        def factor():
            if peek() is None:
                raise ValueError("the address is incomplete")
            t = take()
            if t in ("[", "("):
                v = total()
                if peek() != {"[": "]", "(": ")"}[t]:
                    raise ValueError("missing closing bracket")
                take()
                return self.read_u32(v & 0xFFFFFFFF) if t == "[" else v
            if t in self.symbols:
                return self.resolve(self.symbols[t])
            try:
                return int(t, 16)
            except ValueError:
                raise ValueError("unknown name or number %r" % t)

        def term():
            v = factor()
            while peek() == "*":
                take()
                v *= factor()
            return v

        def total():
            v = term()
            while peek() in ("+", "-"):
                v = v + term() if take() == "+" else v - term()
            return v

        value = total()
        if peek() is not None:
            raise ValueError("unexpected %r in the address" % peek())
        return value & 0xFFFFFFFF
