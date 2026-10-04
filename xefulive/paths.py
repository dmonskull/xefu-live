import os


def data_dir():
    """Where config, mod tables, dumps and screenshots are kept."""
    env = os.environ.get("XEFULIVE_HOME")
    if env:
        return env
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # running from a source checkout: keep everything next to the code
    if os.path.isfile(os.path.join(here, "pyproject.toml")) and os.access(here, os.W_OK):
        return here
    return os.path.join(os.path.expanduser("~"), ".xefulive")


def path(*parts):
    return os.path.join(data_dir(), *parts)


def bundled_tables():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "tables")
