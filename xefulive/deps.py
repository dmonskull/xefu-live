"""py-xbdm is not on PyPI, so find a copy on disk or fetch it from GitHub."""
import io
import os
import shutil
import ssl
import subprocess
import sys
import urllib.error
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


def _download(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read()
    except urllib.error.URLError as e:
        if not isinstance(e.reason, ssl.SSLError):
            raise
    # python.org builds for macOS come without root certificates, so https fails
    # until "Install Certificates" is run. curl uses the system's certificates.
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(url, timeout=30, context=context) as r:
            return r.read()
    except (ImportError, urllib.error.URLError):
        pass
    curl = shutil.which("curl")
    if not curl:
        raise OSError("this Python cannot verify https certificates and curl is not installed")
    return subprocess.run([curl, "-fsSL", url], capture_output=True, timeout=60, check=True).stdout


def fetch(url=ZIP_URL):
    """Download py-xbdm and unpack it into a py-xbdm folder in the data folder."""
    parent = paths.data_dir()
    os.makedirs(parent, exist_ok=True)
    archive = zipfile.ZipFile(io.BytesIO(_download(url)))
    top = archive.namelist()[0].split("/")[0]
    target = os.path.join(parent, "py-xbdm")
    archive.extractall(parent)
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.rename(os.path.join(parent, top), target)
    return target
