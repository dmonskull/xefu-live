import sys


def _get_py_xbdm():
    """First start without py-xbdm: offer to download it."""
    import tkinter as tk
    from tkinter import messagebox
    from . import deps
    root = tk.Tk()
    root.withdraw()
    try:
        if not messagebox.askyesno("Xefu Live", "Xefu Live needs py-xbdm to talk to the console.\n\n"
                                   "Download it now from\n%s ?" % deps.REPO):
            return False
        try:
            deps.fetch()
        except Exception as e:
            messagebox.showerror("Xefu Live", "The download failed (%s).\n\nGet py-xbdm from %s yourself and put "
                                 "the folder next to xefulive, named py-xbdm." % (e, deps.REPO))
            return False
        return deps.find() is not None
    finally:
        root.destroy()


def main():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        sys.exit("This Python was built without tkinter. Install it (python3-tk on Linux, "
                 "python-tk with Homebrew) or use the python.org installer.")
    from . import deps
    if deps.find() is None and not _get_py_xbdm():
        sys.exit("py-xbdm is missing. Get it from %s" % deps.REPO)
    from .ui.main import App
    App(sys.argv[1] if len(sys.argv) > 1 else None).run()


if __name__ == "__main__":
    main()
