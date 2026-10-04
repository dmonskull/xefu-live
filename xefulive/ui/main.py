import sys
import tkinter as tk
import traceback
from tkinter import ttk

from ..session import Session
from .changes import ChangesTab
from .common import HEADING, MONO, Tasks, palette, setup_fonts
from .memory import MemoryTab
from .modstab import ModsTab
from .search import SearchTab
from .tools import ToolsTab


class App:
    def __init__(self, host=None):
        self.root = tk.Tk()
        self.root.title("Xefu Live")
        self.root.geometry("1220x800")
        self.root.minsize(1040, 680)
        setup_fonts(self.root)
        self.pal = palette(self.root)
        ttk.Style(self.root).configure("Mono.Treeview", font=MONO, rowheight=22)
        self.root.report_callback_exception = self._callback_error

        self.s = Session()
        if host:
            self.s.config["host"] = host
        self.tasks = Tasks(self.root, self.fail)
        self.busy = False
        self.busy_label = ""
        self._progress = None
        self._game_key = None
        self._checking = False

        header = ttk.Frame(self.root, padding=(12, 10, 12, 6))
        header.pack(fill="x")
        self.dot = tk.Canvas(header, width=14, height=14, highlightthickness=0, bd=0)
        self.dot.pack(side="left")
        self.dot_item = self.dot.create_oval(2, 2, 12, 12, fill=self.pal["warn"], outline="")
        self.status = ttk.Label(header, text="Connecting to the console...", font=HEADING)
        self.status.pack(side="left", padx=8)
        ttk.Button(header, text="Screenshot", command=self.screenshot).pack(side="right")
        self.pause_btn = ttk.Button(header, text="Pause game", command=self.toggle_pause)
        self.pause_btn.pack(side="right", padx=6)

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=10)
        self.memory = MemoryTab(self.nb, self)
        self.search = SearchTab(self.nb, self)
        self.changes = ChangesTab(self.nb, self)
        self.mods = ModsTab(self.nb, self)
        self.tools = ToolsTab(self.nb, self)
        self.tabs = (self.memory, self.search, self.changes, self.mods, self.tools)
        for tab, name in zip(self.tabs, ("Memory", "Search", "Changes", "Mods", "Tools")):
            self.nb.add(tab, text="  %s  " % name)

        footer = ttk.Frame(self.root, padding=(12, 6, 12, 8))
        footer.pack(fill="x")
        self.message = ttk.Label(footer, text="", foreground=self.pal["dim"])
        self.message.pack(side="left")
        self.pbar = ttk.Progressbar(footer, length=260, mode="determinate", maximum=1000)
        self.plabel = ttk.Label(footer, text="", foreground=self.pal["dim"])

        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(100, self._poll)

    def _poll(self):
        self.poll_now()
        self.root.after(3000, self._poll)

    def poll_now(self):
        if self._checking:
            return
        self._checking = True

        def done(_):
            self._checking = False
            self._update_status()

        self.tasks.run(self.s.check, done, done)

    def _update_status(self):
        s = self.s
        self.status.configure(text=s.summary())
        colour = self.pal["ok"] if s.running else self.pal["warn"] if s.console else self.pal["bad"]
        self.dot.itemconfigure(self.dot_item, fill=colour)
        self.pause_btn.configure(text="Resume game" if s.paused else "Pause game")
        # a new game (or the same game restarted) means every tab has to start over
        key = (s.guest.xbe["title_id"], s.guest.ram_base) if s.running else None
        if key != self._game_key:
            self._game_key = key
            if key:
                for tab in self.tabs:
                    tab.on_game()
                self.say("Found %s running under %s." % (s.guest.xbe["title"], s.guest.emulator))

    def visible(self, tab):
        try:
            return self.nb.nametowidget(self.nb.select()) is tab
        except Exception:
            return False

    def say(self, text):
        self.message.configure(text=text, foreground=self.pal["dim"])

    def fail(self, err):
        text = str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err)
        self.message.configure(text=text or type(err).__name__, foreground=self.pal["bad"])
        self.root.bell()

    def _callback_error(self, exc, val, tb):
        traceback.print_exception(exc, val, tb, file=sys.stderr)
        self.fail(val)

    def job(self, label, fn, done=None):
        """Run fn(progress) in the background with a progress bar. One job at a time."""
        if self.busy:
            self.say("Still working on: %s" % self.busy_label)
            return False
        self.busy, self.busy_label = True, label
        state = {"done": 0, "total": 1}
        self._progress = state
        self.pbar.configure(value=0)
        self.plabel.configure(text=label + "...")
        self.plabel.pack(side="right", padx=(0, 10))
        self.pbar.pack(side="right")

        def progress(d, t):
            state["done"], state["total"] = d, t

        def finish():
            self.busy = False
            self._progress = None
            self.pbar.pack_forget()
            self.plabel.pack_forget()

        def ok(result):
            finish()
            if done:
                done(result)

        def bad(err):
            finish()
            self.fail(err)

        self.tasks.run(lambda: fn(progress), ok, bad)
        self._progress_tick()
        return True

    def _progress_tick(self):
        state = self._progress
        if state is None:
            return
        part = state["done"] / max(1, state["total"])
        self.pbar.configure(value=1000 * part)
        self.plabel.configure(text="%s...  %d%%" % (self.busy_label, 100 * part))
        self.root.after(150, self._progress_tick)

    def goto(self, addr):
        self.nb.select(self.memory)
        self.memory.show(addr)

    def add_mod(self, address, vtype):
        self.nb.select(self.mods)
        self.mods.add(address, vtype)

    def toggle_pause(self):
        want = not self.s.paused

        def done(_):
            self._update_status()
            self.say("The game is paused." if want else "The game is running again.")

        self.tasks.run(lambda: self.s.pause(want), done)

    def screenshot(self):
        self.say("Taking a screenshot...")
        self.tasks.run(self.s.screenshot, self._show_screenshot)

    def _show_screenshot(self, path):
        from PIL import Image, ImageTk
        image = Image.open(path)
        if image.width > 960:
            image = image.resize((960, int(image.height * 960 / image.width)))
        win = tk.Toplevel(self.root)
        win.title("Screenshot")
        photo = ImageTk.PhotoImage(image, master=win)
        label = ttk.Label(win, image=photo)
        label.image = photo     # keep a reference or Tk drops the picture
        label.pack()
        ttk.Label(win, text=path, foreground=self.pal["dim"], padding=6).pack()
        self.say("Screenshot saved to %s" % path)

    def quit(self):
        self.s.shutdown()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
