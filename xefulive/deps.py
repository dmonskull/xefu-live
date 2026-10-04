"""py-xbdm is not on PyPI, so find a copy on disk or fetch it from GitHub."""
import io
import os
import shutil
import sys
import urllib.request
import zipfile

from . import paths

REPO = "https://github.com/XeCrippy/py-xbdm"
ZIP_URL = REPO + "/archive/refs/heads/master.zip"


def _candidates():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [os.environ.get("PY_XBDM_PATH", ""),
            os.path.join(here, "py-xbdm"),
            os.path.join(here, "py-xbdm-master"),
            paths.path("py-xbdm")]


def find():
    """Put py-xbdm on sys.path. Returns the folder used, '' if it was importable already, None if missing."""
    for folder in _candidates():
        if folder and os.path.isfile(os.path.join(folder, "py_xbdm", "client.py")):
            if folder not in sys.path:
                sys.path.insert(0, folder)
            return folder
    try:
        import py_xbdm  # noqa: F401
        return ""
    except ImportError:
        return None


def fetch(url=ZIP_URL):
    """Download py-xbdm and unpack it into a py-xbdm folder in the data folder."""
    parent = paths.data_dir()
    os.makedirs(parent, exist_ok=True)
    with urllib.request.urlopen(url, timeout=30) as r:
        archive = zipfile.ZipFile(io.BytesIO(r.read()))
    top = archive.namelist()[0].split("/")[0]
    target = os.path.join(parent, "py-xbdm")
    archive.extractall(parent)
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.rename(os.path.join(parent, top), target)
    return target
