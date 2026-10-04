"""Console connection, built on py-xbdm (https://github.com/XeCrippy/py-xbdm).

py-xbdm reads memory with the text getmem command, which is slow on a 360
(about 7 KB/s). This adds the binary getmemex command and a small pool of
connections so big reads run in parallel (about 400 KB/s).
"""
import contextlib
import queue
import struct
import threading
from concurrent.futures import ThreadPoolExecutor

from . import deps

if deps.find() is None:
    raise ImportError("py-xbdm was not found. Get it from %s and put the folder next to xefulive "
                      "as 'py-xbdm', or set PY_XBDM_PATH." % deps.REPO)

from py_xbdm import discovery  # noqa: E402
from py_xbdm.client import XBDMClient  # noqa: E402
from py_xbdm.connection import XBDMConnection  # noqa: E402


class XbdmError(Exception):
    def __init__(self, code, message):
        super().__init__("%d %s" % (code, message))
        self.code = code


class Unreadable(Exception):
    pass


class Client(XBDMClient):
    """One connection. The pool hands it to one thread at a time."""

    def __init__(self, host, timeout=10.0):
        # skip XBDMClient.__init__: the stock one scans the network for a console,
        # and we already know which one we want
        self.conn = XBDMConnection(host, timeout=timeout)
        self._lock = threading.RLock()
        self._host = host
        self._flush_stub_addr = 0
        self._flush_stub_size = 0
        self.conn.connect()
        self._status()

    def _line(self):
        return self.conn.recv_line().decode("ascii", "replace").strip()

    def _status(self):
        text = self._line()
        try:
            code = int(text[:3])
        except ValueError:
            raise ConnectionError("unexpected reply from the console: %r" % text)
        if code >= 400:
            raise XbdmError(code, text[4:].strip())
        return code, text[4:].strip()

    def command(self, text):
        self.conn.send(text.encode("ascii") + b"\r\n")
        return self._status()

    def lines(self, text):
        code, _ = self.command(text)
        out = []
        while code == 202:
            line = self._line()
            if line == ".":
                break
            out.append(line)
        return out

    def read(self, address, size):
        # getmemex sends blocks of up to 0x400 bytes, each with a 2 byte header:
        # low 15 bits = byte count, top bit = last block
        self.command("getmemex addr=0x%X length=0x%X" % (address, size))
        out = bytearray()
        while True:
            flags = struct.unpack("<H", self.conn.recv_exact(2))[0]
            count = flags & 0x7FFF
            if count:
                out += self.conn.recv_exact(count)
            if flags & 0x8000 or len(out) >= size:
                break
        if len(out) < size:
            raise Unreadable("memory at %08X is not readable" % (address + len(out)))
        return bytes(out[:size])

    def write(self, address, data):
        # xbdm caps the command line length, so write in small pieces
        for off in range(0, len(data), 0x80):
            self.command("setmem addr=0x%X data=%s" % (address + off, data[off:off + 0x80].hex()))


class Console:
    """A small pool of connections to one console."""

    CHUNK = 0x20000

    def __init__(self, host, pool_size=6, timeout=10.0):
        self.host = host
        self.pool_size = pool_size
        self.timeout = timeout
        self._free = queue.LifoQueue()
        self._count = 0
        self._lock = threading.Lock()

    def _get(self):
        try:
            return self._free.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            can_open = self._count < self.pool_size
            if can_open:
                self._count += 1
        if can_open:
            try:
                return Client(self.host, self.timeout)
            except Exception:
                # xbdm only allows a few connections; fall back to waiting for one of ours
                with self._lock:
                    self._count -= 1
                    have_others = self._count > 0
                if not have_others:
                    raise
        return self._free.get(timeout=self.timeout * 6)

    @contextlib.contextmanager
    def client(self):
        c = self._get()
        try:
            yield c
        except (Unreadable, XbdmError):
            self._free.put(c)       # the connection itself is still good
            raise
        except Exception:
            with self._lock:
                self._count -= 1
            with contextlib.suppress(Exception):
                c.close()
            raise
        else:
            self._free.put(c)

    def close(self):
        while True:
            try:
                c = self._free.get_nowait()
            except queue.Empty:
                break
            with contextlib.suppress(Exception):
                c.close()
        with self._lock:
            self._count = 0

    def read(self, address, size):
        if size <= 0:
            return b""
        with self.client() as c:
            return c.read(address, size)

    def write(self, address, data):
        with self.client() as c:
            c.write(address, data)

    def read_many(self, spans, progress=None):
        """Read [(address, size), ...] in parallel. Unreadable spans come back as None."""
        jobs = []
        for i, (address, size) in enumerate(spans):
            for off in range(0, size, self.CHUNK):
                jobs.append((i, off, address + off, min(self.CHUNK, size - off)))
        outs = [bytearray(size) for _, size in spans]
        bad = set()
        total = sum(j[3] for j in jobs) or 1
        done = [0]
        lock = threading.Lock()

        def run(job):
            i, off, address, n = job
            try:
                outs[i][off:off + n] = self.read(address, n)
            except (Unreadable, XbdmError):
                bad.add(i)
            with lock:
                done[0] += n
                if progress:
                    progress(done[0], total)

        if len(jobs) <= 1:
            for job in jobs:
                run(job)
        else:
            with ThreadPoolExecutor(max_workers=self.pool_size) as pool:
                list(pool.map(run, jobs))
        return [None if i in bad else bytes(o) for i, o in enumerate(outs)]

    def command(self, text):
        with self.client() as c:
            return c.command(text)

    def name(self):
        return self.command("dbgname")[1]

    def regions(self):
        out = []
        with self.client() as c:
            for line in c.lines("walkmem"):
                f = dict(p.split("=") for p in line.split() if "=" in p)
                out.append((int(f["base"], 16), int(f["size"], 16)))
        return out

    def screenshot(self, folder):
        with self.client() as c:
            # the console can take a few seconds to hand over a frame
            c.conn.timeout = 30.0
            try:
                return c.screenshot(folder)
            finally:
                c.conn.timeout = self.timeout
                if c.conn.sock:
                    c.conn.sock.settimeout(self.timeout)


def discover():
    """Find consoles on the local network. Returns [(ip, name), ...]."""
    with contextlib.redirect_stdout(None):      # py-xbdm prints its progress
        try:
            found = discovery.discover_xbdm_with_names(find_all=True)
            if found:
                return list(found)
        except Exception:
            pass
        try:
            return [(ip, "") for ip in discovery.discover_xbdm(find_all=True)]
        except Exception:
            return []
