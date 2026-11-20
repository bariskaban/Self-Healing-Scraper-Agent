"""Display names for documents: Content-Disposition, URLs and names inside ZIPs. Never used as paths."""
from __future__ import annotations

import mimetypes
import re
import zipfile
from collections.abc import Iterable
from urllib.parse import unquote, urlsplit

DEFAULT_NAME = "document"
MAX_NAME_CHARS = 200

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _fix_latin1_utf8(name: str) -> str:
    """Undo raw UTF-8 bytes read as Latin-1 (servers often send them in filename=)."""
    try:
        fixed = name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name
    return fixed


def split_path(name: str) -> list[str]:
    """Split a name on / and \\, dropping empty, '.' and '..' parts and control characters."""
    parts = []
    for part in name.replace("\\", "/").split("/"):
        part = _CONTROL.sub("", part).strip()
        if part and part not in (".", ".."):
            parts.append(part)
    return parts


def clean_name(name: str | None) -> str | None:
    """Base name only, no path or control characters, at most MAX_NAME_CHARS; None if nothing is left."""
    if not name:
        return None
    parts = split_path(name)
    if not parts:
        return None
    base = parts[-1]
    if len(base) > MAX_NAME_CHARS:
        stem, dot, ext = base.rpartition(".")
        if dot and len(ext) <= 10:
            base = stem[: MAX_NAME_CHARS - len(ext) - 1] + "." + ext
        else:
            base = base[:MAX_NAME_CHARS]
    return base


_CD_PARAM = re.compile(
    r""";\s*([!#$%&'*+.^_`|~0-9A-Za-z-]+)\s*=\s*("(?:[^"\\]|\\.)*"|[^;]*)""")


def _cd_params(value: str) -> dict[str, str]:
    """Parameters of a Content-Disposition value, names lowercased, quoted strings unescaped."""
    params: dict[str, str] = {}
    for m in _CD_PARAM.finditer(value):
        key, val = m.group(1).lower(), m.group(2).strip()
        if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
            val = re.sub(r'\\(.)', r'\1', val[1:-1])
        params.setdefault(key, val)
    return params


def _decode_ext_value(value: str) -> str | None:
    """RFC 5987 ext-value: charset'language'percent-encoded."""
    charset, sep, rest = value.partition("'")
    if not sep:
        return None
    _, sep, encoded = rest.partition("'")
    if not sep:
        return None
    try:
        return unquote(encoded, encoding=charset.strip() or "utf-8", errors="strict")
    except (LookupError, UnicodeDecodeError):
        return None


def name_from_content_disposition(value: str | None) -> str | None:
    """File name from a Content-Disposition header (RFC 6266), preferring filename* (RFC 5987)."""
    if not value:
        return None
    params = _cd_params(";" + value.split(";", 1)[1] if ";" in value else "")
    if "filename*" in params:
        name = clean_name(_decode_ext_value(params["filename*"]))
        if name:
            return name
    if params.get("filename"):
        return clean_name(_fix_latin1_utf8(params["filename"]))
    return None


def name_from_url(url: str | None) -> str | None:
    """Last path segment of a URL, percent-decoded."""
    if not url:
        return None
    path = urlsplit(url).path
    return clean_name(unquote(path.rsplit("/", 1)[-1]))


def with_extension(name: str, content_type: str | None) -> str:
    """Add an extension guessed from the content type when the name has none."""
    if "." in name.strip(".") or not content_type:
        return name
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip().lower())
    return name + ext if ext else name


def choose_name(announced: str | None, content_disposition: str | None, url: str | None,
                content_type: str | None = None) -> str:
    """The portal's announced name, else Content-Disposition, else the URL, else 'document'."""
    name = (clean_name(announced) or name_from_content_disposition(content_disposition)
            or name_from_url(url) or DEFAULT_NAME)
    return with_extension(name, content_type)


def zip_entry_name(info: zipfile.ZipInfo) -> str:
    """Decoded name of a ZIP entry: UTF-8 flag or Unicode path field, else UTF-8 if valid, else CP437."""
    if info.flag_bits & 0x800 or info.filename != info.orig_filename:
        return info.filename
    raw = info.orig_filename.encode("cp437")  # zipfile decoded the raw bytes as CP437: lossless
    try:
        return raw.decode("utf-8")  # many tools write UTF-8 without setting the flag
    except UnicodeDecodeError:
        return info.orig_filename


def unique_names(paths: Iterable[str]) -> list[str]:
    """fileName for each entry path: the base name; on a clash the folder path joined with ' - ';
    if that clashes too, a ' (2)', ' (3)' suffix. Compared without case."""
    paths = list(paths)
    bases = [split_path(p)[-1] if split_path(p) else DEFAULT_NAME for p in paths]
    counts: dict[str, int] = {}
    for b in bases:
        counts[b.casefold()] = counts.get(b.casefold(), 0) + 1
    out: list[str] = []
    taken: set[str] = set()
    for path, base in zip(paths, bases):
        name = base if counts[base.casefold()] == 1 else " - ".join(split_path(path)) or base
        candidate, n = name, 1
        while candidate.casefold() in taken:
            n += 1
            stem, dot, ext = name.rpartition(".")
            candidate = f"{stem} ({n}).{ext}" if dot and stem else f"{name} ({n})"
        taken.add(candidate.casefold())
        out.append(clean_name(candidate) or DEFAULT_NAME)
    return out
