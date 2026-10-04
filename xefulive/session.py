"""One console and whatever original Xbox game is running on it."""
import json
import os
import threading
import time

from . import paths
from .guest import Guest, NotRunning
from .mods import ModTable
from .xbdm import Console, Unreadable, XbdmError, discover

AREAS = (
    ("data", "Game data (the XBE's writable sections)"),
    ("heap", "Heap (memory the game allocated)"),
    ("all", "All game memory (data + heap)"),
    ("image", "Whole XBE image (code + data)"),
    ("custom", "Custom range"),
)
READ_SPEED = 430 * 1024     # bytes per second with six connections, for the time estimates


class Session:
    def __init__(self):
        self.config = {}
        try:
            with open(paths.path("config.json")) as f:
                self.config = json.load(f)
        except (OSError, ValueError):
            pass
        self.console = None
        self.guest = None
        self.mods = None
        self.console_name = ""
        self.paused = False
        self.problem = "Not connected yet"
        self._xbe_host = None
        self._lock = threading.RLock()

    def connect(self, host=None):
        with self._lock:
            host = (host or self.config.get("host") or "").strip()
            if not host:
                found = discover()
                if not found:
                    self.problem = "No console found on the network. Type its IP address in Tools."
                    raise ValueError(self.problem)
                host = found[0][0]
            if self.console:
                self.console.close()
            if self.mods:
                self.mods.unfreeze_all()
            console = Console(host, pool_size=int(self.config.get("connections", 6)))
            try:
                self.console_name = console.name()
            except Exception as e:
                self.console = None
                self.problem = "Cannot reach a console at %s (%s)" % (host, e)
                raise ValueError(self.problem)
            self.console = console
            self.guest = Guest(console)
            self.mods = ModTable(self.guest)
            self._xbe_host = None
            self.paused = False
            self.config["host"] = host
            os.makedirs(paths.data_dir(), exist_ok=True)
            with open(paths.path("config.json"), "w") as f:
                json.dump(self.config, f, indent=2)
            self._detect()

    def _detect(self):
        try:
            self.guest.detect()
        except NotRunning as e:
            self.problem = "Connected to %s, but %s. Start an original Xbox game." % (self.console_name or "the console", e)
            self._xbe_host = None
            return
        x = self.guest.xbe
        if not x:
            self.problem = "The emulator is starting, the game has not loaded yet."
            self._xbe_host = None
            return
        self.problem = ""
        self._xbe_host = self.guest.host(0x10000)
        if self.mods.title_id != x["title_id"]:
            self.mods.unfreeze_all()
            self.mods.load_for(x["title_id"], x["title"])

    def check(self):
        """Cheap health check, called every few seconds."""
        with self._lock:
            if not self.console:
                try:
                    self.connect()
                except ValueError:
                    return False
            elif self._xbe_host is None:
                try:
                    self._detect()
                except Exception as e:
                    self.problem = "Lost contact with the console (%s)" % e
            else:
                # the XBE header is still where we found it = same game still running
                try:
                    if self.console.read(self._xbe_host, 4) != b"XBEH":
                        self._detect()
                except (Unreadable, XbdmError):
                    self._detect()
                except Exception as e:
                    self.problem = "Lost contact with the console (%s)" % e
                    self._xbe_host = None
            return self.running

    @property
    def running(self):
        return bool(self.guest and self.guest.ram_base and self.guest.xbe and not self.problem)

    def need_game(self):
        if not self.running:
            raise NotRunning(self.problem or "no original Xbox game is running")
        return self.guest

    def summary(self):
        if not self.running:
            return self.problem
        x = self.guest.xbe
        return "%s  |  title %s  |  %s  |  %s (%s)" % (
            x["title"], x["title_id"], self.guest.emulator, self.console_name, self.config.get("host", ""))

    def regions(self, area, lo="", hi=""):
        g = self.need_game()
        custom = (g.resolve(lo), g.resolve(hi)) if area == "custom" else None
        return g.regions(area, custom)

    def areas(self):
        g = self.need_game()
        out = []
        for name, label in AREAS:
            if name == "custom":
                out.append((name, label))
                continue
            try:
                size = sum(n for _, n in g.regions(name))
            except Exception:
                size = 0
            out.append((name, "%s  -  %.1f MB, about %d s" % (label, size / 2 ** 20, max(1, round(size / READ_SPEED)))))
        return out

    def describe(self, addr):
        g = self.need_game()
        phys = g.translate(addr)
        return {"addr": addr, "phys": phys, "host": None if phys is None else g.ram_base + phys,
                "section": g.section_of(addr)}

    def pause(self, want):
        if not self.console:
            raise ValueError("not connected")
        try:
            self.console.command("stop" if want else "go")
        except XbdmError as e:
            text = str(e).lower()
            if "already" not in text and "not stopped" not in text:
                raise ValueError("the console refused: %s" % e)
        self.paused = bool(want)

    def screenshot(self):
        if not self.console:
            raise ValueError("not connected")
        return self.console.screenshot(paths.path("screenshots"))

    def dump(self, regions, progress=None):
        g = self.need_game()
        folder = paths.path("dumps")
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = []
        for (va, size), buf in zip(regions, g.read_ranges(regions, progress)):
            name = os.path.join(folder, "%s_%s_%08X-%08X.bin" % (g.xbe["title_id"], stamp, va, va + size))
            with open(name, "wb") as f:
                f.write(buf)
            out.append(name)
        return out

    def shutdown(self):
        try:
            if self.mods:
                self.mods.unfreeze_all()
            if self.paused and self.console:
                self.console.command("go")
            if self.console:
                self.console.close()
        except Exception:
            pass
