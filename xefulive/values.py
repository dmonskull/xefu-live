"""Value types used by Xbox games (x86, little endian)."""
import re
import struct

import numpy as np

# name: (numpy dtype, size, struct format)
NUMERIC = {
    "u8": ("<u1", 1, "<B"),
    "i8": ("<i1", 1, "<b"),
    "bool": ("<u1", 1, "<B"),
    "u16": ("<u2", 2, "<H"),
    "i16": ("<i2", 2, "<h"),
    "u32": ("<u4", 4, "<I"),
    "i32": ("<i4", 4, "<i"),
    "u64": ("<u8", 8, "<Q"),
    "i64": ("<i8", 8, "<q"),
    "float": ("<f4", 4, "<f"),
    "double": ("<f8", 8, "<d"),
}
ALL = tuple(NUMERIC) + ("bytes", "text", "text16")
LABELS = {
    "u8": "Byte (0 to 255)",
    "i8": "Signed byte",
    "bool": "Bool (true / false)",
    "u16": "2 bytes",
    "i16": "2 bytes, signed",
    "u32": "4 bytes",
    "i32": "4 bytes, signed",
    "u64": "8 bytes",
    "i64": "8 bytes, signed",
    "float": "Float",
    "double": "Double",
    "bytes": "Bytes (hex)",
    "text": "Text",
    "text16": "Text (UTF-16)",
}


def is_float(t):
    return t in ("float", "double")


def size_of(t):
    return NUMERIC[t][1]


def dtype(t):
    return np.dtype(NUMERIC[t][0])


def parse(t, text):
    s = str(text).strip()
    if t == "bool":
        if s.lower() in ("true", "t", "yes", "on"):
            return 1
        if s.lower() in ("false", "f", "no", "off"):
            return 0
    if is_float(t):
        return float(s)
    value = int(s, 16) if s.lower().startswith(("0x", "-0x")) else int(s, 10)
    lo, hi = np.iinfo(dtype(t)).min, np.iinfo(dtype(t)).max
    if not lo <= value <= hi:
        raise ValueError("%s does not fit in %s (%d to %d)" % (s, LABELS[t].lower(), lo, hi))
    return value


def tolerance(t, text):
    # games show floats rounded, so "500" should match 499.5 to 500.5 and "12.5" 12.45 to 12.55
    if not is_float(t):
        return 0
    s = str(text).strip().lower()
    if "e" in s:
        return abs(float(s)) * 1e-6
    digits = len(s.split(".")[1]) if "." in s else 0
    return 0.5 * 10 ** -digits


def parse_pattern(text):
    """'DE AD ?? EF' -> (bytes, list of which positions are fixed)."""
    parts = re.findall(r"[0-9A-Fa-f]{2}|\?\??", str(text).replace(",", " "))
    if not parts or "".join(parts) != re.sub(r"[\s,]+", "", str(text)):
        raise ValueError("bytes must be hex pairs like DE AD BE EF (use ?? for any byte)")
    data = bytes(0 if p.startswith("?") else int(p, 16) for p in parts)
    return data, [not p.startswith("?") for p in parts]


def encode(t, value):
    if t in NUMERIC:
        return struct.pack(NUMERIC[t][2], parse(t, value))
    if t == "bytes":
        data, mask = parse_pattern(value)
        if not all(mask):
            raise ValueError("?? only works when searching, not when writing")
        return data
    if t == "text":
        return str(value).encode("latin-1", "replace")
    if t == "text16":
        return str(value).encode("utf-16le")
    raise ValueError("unknown type %r" % t)


def decode(t, raw):
    if t in NUMERIC:
        n = NUMERIC[t][1]
        if len(raw) < n:
            return None
        v = struct.unpack(NUMERIC[t][2], raw[:n])[0]
        if t == "bool":
            return "true" if v == 1 else "false" if v == 0 else "true (%d)" % v
        return fmt_float(v) if is_float(t) else v
    if t == "bytes":
        return raw.hex(" ").upper()
    if t == "text":
        return raw.split(b"\0")[0].decode("latin-1")
    if t == "text16":
        return raw[:len(raw) & ~1].decode("utf-16le", "replace").split("\0")[0]
    return None


def fmt_float(v):
    if v != v:
        return "NaN"
    if v in (float("inf"), float("-inf")):
        return "inf" if v > 0 else "-inf"
    if v == 0:
        return "0"
    if 1e-4 <= abs(v) < 1e9:
        return ("%.6f" % v).rstrip("0").rstrip(".")
    return "%.6g" % v


def show_all(raw):
    out = {t: decode(t, raw) for t in ("u8", "i8", "u16", "i16", "u32", "i32", "float", "double")}
    if len(raw) >= 4:
        out["u32_hex"] = "%08X" % struct.unpack("<I", raw[:4])[0]
    out["text"] = "".join(chr(b) if 32 <= b < 127 else "." for b in raw[:16])
    return out
