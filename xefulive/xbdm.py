"""Console connection, built on py-xbdm (https://github.com/XeCrippy/py-xbdm).

py-xbdm reads memory with the text getmem command, which is slow on a 360
(about 7 KB/s). This adds the binary getmemex command, and runs everything
over a single connection with a request queue.
"""
import contextlib
import itertools
import queue
import struct
import threading
from concurrent.futures import Future

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


class Cancelled(Exception):
    pass


class Client(XBDMClient):
    def __init__(self, host, timeout=8.0):
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
    """The one connection to the console.

    A worker thread owns the socket and takes requests from a priority queue.
    Big reads are cut into pieces that go in at low priority, so a click or a
    live value never waits behind a long scan, only behind one piece of it.

    While a game runs XBDM only gets a little CPU time (about 100 KB/s, 28 ms
    per request). With the game stopped the same connection does about 1.4 MB/s,
    so big reads stop the game for as long as they take.
    """

    BIG = 0x40000       # reads from this size up count as big

    def __init__(self, host, timeout=8.0):
        self.host = host
        self.timeout = timeout
        self.pause_big_reads = True
        self.stopped = False        # the user paused the game
        self.holding = False        # we paused it for a big read
        self._owe_go = False
        self._client = None
        self._queue = queue.PriorityQueue()
        self._order = itertools.count()
        self._thread = threading.Thread(target=self._work, daemon=True)
        self._thread.start()

    def _submit(self, fn, priority=0):
        future = Future()
        self._queue.put((priority, next(self._order), fn, future))
        return future

    def _work(self):
        while True:
            _, _, fn, future = self._queue.get()
            if fn is None:
                break
            if not future.set_running_or_notify_cancel():
                continue
            try:
                if self._client is None:
                    self._client = Client(self.host, self.timeout)
                    if self._owe_go:    # we lost the connection while holding the game stopped
                        with contextlib.suppress(XbdmError):
                            self._client.command("go")
                        self._owe_go = False
                future.set_result(fn(self._client))
            except (Unreadable, XbdmError) as e:
                future.set_exception(e)     # the connection itself is fine
            except Exception as e:
                self._drop()
                future.set_exception(e)
                self._fail_waiting(e)
        self._fail_waiting(ConnectionError("disconnected"))
        self._drop()

    def _drop(self):
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.close()
            self._client = None

    def _fail_waiting(self, error):
        # the console went quiet: fail what is queued now instead of letting each request time out in turn
        waiting = []
        while True:
            try:
                waiting.append(self._queue.get_nowait())
            except queue.Empty:
                break
        for item in waiting:
            if item[2] is None:
                self._queue.put(item)
            elif item[3].set_running_or_notify_cancel():
                item[3].set_exception(error)

    def close(self):
        self._queue.put((-1, next(self._order), None, None))

    def read(self, address, size):
        if size <= 0:
            return b""
        return self._submit(lambda c: c.read(address, size)).result()

    def write(self, address, data):
        self._submit(lambda c: c.write(address, data)).result()

    def command(self, text):
        return self._submit(lambda c: c.command(text)).result()

    def name(self):
        return self.command("dbgname")[1]

    def regions(self):
        out = []
        for line in self._submit(lambda c: c.lines("walkmem")).result():
            f = dict(p.split("=") for p in line.split() if "=" in p)
            out.append((int(f["base"], 16), int(f["size"], 16)))
        return out

    def pause(self, want):
        try:
            self.command("stop" if want else "go")
        except XbdmError as e:
            if e.code not in (408, 426):    # "not stopped" / "already stopped"
                raise
        self.stopped = bool(want)

    @contextlib.contextmanager
    def quiet(self, size):
        """Stop the game for the duration of a big read (it is about 10x faster and gives one consistent picture)."""
        mine = False
        if self.pause_big_reads and size >= self.BIG and not self.stopped and not self.holding:
            try:
                self.command("stop")
                mine = self.holding = True
            except XbdmError:
                pass        # already stopped by something else, leave it that way
        try:
            yield
        finally:
            if mine:
                self.holding = False
                try:
                    self.command("go")
                except XbdmError:
                    pass
                except Exception:
                    self._owe_go = True

    def read_many(self, spans, progress=None):
        """Read [(address, size), ...]. Unreadable spans come back as None.

        progress(done, total) is called as pieces arrive and may raise Cancelled to stop early.
        """
        total = sum(size for _, size in spans)
        priority = 1 if total >= self.BIG else 0
        # with the game stopped a piece takes milliseconds, so they can be bigger
        step = 0x20000 if self.holding or self.stopped else 0x8000
        outs = [bytearray(size) for _, size in spans]
        pieces = []
        for i, (address, size) in enumerate(spans):
            for off in range(0, size, step):
                n = min(step, size - off)
                pieces.append((i, off, n, self._submit(lambda c, a=address + off, n=n: c.read(a, n), priority)))
        bad = set()
        done = 0
        try:
            for i, off, n, future in pieces:
                try:
                    outs[i][off:off + n] = future.result()
                except (Unreadable, XbdmError):
                    bad.add(i)
                done += n
                if progress:
                    progress(done, total or 1)
        except BaseException:
            for piece in pieces:
                piece[3].cancel()
            raise
        return [None if i in bad else bytes(o) for i, o in enumerate(outs)]

    def screenshot(self, folder):
        def shot(c):
            # the console can take a few seconds to hand over a frame
            c.conn.timeout = 30.0
            try:
                return c.screenshot(folder)
            finally:
                c.conn.timeout = self.timeout
                if c.conn.sock:
                    c.conn.sock.settimeout(self.timeout)
        return self._submit(shot).result()


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
