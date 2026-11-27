"""Native .cadz format: a ZIP with JSON inside. See docs/FILE_FORMAT.md."""
from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
import zipfile
from typing import Callable

from .. import APP_NAME, __version__
from ..core.model import Document, Header, Layer, Linetype, entity_from_dict, entity_to_dict
from ..core.model.tables import BlockDefinition, DimStyle, Group, Layout

FORMAT_NAME = "cadz"
FORMAT_VERSION = (1, 4, 0)   # 1.1: blocks…, constraints; 1.2: associativity, arrays; 1.3: solids, sketches; 1.4: hole shapes
KNOWN_MEMBERS = {"manifest.json", "document.json", "thumbnail.png"}


class FileFormatError(Exception):
    pass


def _version_str(v: tuple[int, int, int]) -> str:
    return ".".join(str(x) for x in v)


def _parse_version(text: str) -> tuple[int, int, int]:
    try:
        parts = [int(x) for x in text.split(".")]
    except ValueError as exc:
        raise FileFormatError(f"Bad format version '{text}'") from exc
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


# Migrations upgrade the document.json dict one version at a time:
#   MIGRATIONS[(1, 0)] = function converting a 1.0 dict into a 1.1 dict
MIGRATIONS: dict[tuple[int, int], tuple[tuple[int, int], Callable[[dict], dict]]] = {}


def _migrate(data: dict, version: tuple[int, int, int]) -> dict:
    key = (version[0], version[1])
    while key in MIGRATIONS:
        key, fn = MIGRATIONS[key]
        data = fn(data)
    return data


def document_to_dict(doc: Document) -> dict:
    d = dict(doc.extra)
    d.update({
        "header": doc.header.to_dict(),
        "layers": [layer.to_dict() for layer in doc.layers.values()],
        "linetypes": [lt.to_dict() for lt in doc.linetypes.values()],
        "entities": [entity_to_dict(e) for e in doc.entities.values()],
        "next_handle": doc.next_handle,
        "blocks": [b.to_dict() for b in doc.blocks.values()],
        "dimstyles": [s.to_dict() for s in doc.dimstyles.values()],
        "groups": [g.to_dict() for g in doc.groups.values()],
        "layouts": [lo.to_dict() for lo in doc.layouts.values()],
    })
    if doc.sketches:
        d["sketches"] = [sk.to_dict() for sk in doc.sketches.values()]
    if doc.constraints:
        from ..core.constraints.model import constraints_to_list
        d["constraints"] = constraints_to_list(doc.constraints)
    return d


def document_from_dict(data: dict) -> Document:
    doc = Document()
    known = {"header", "layers", "linetypes", "entities", "next_handle", "blocks", "dimstyles", "groups",
             "layouts", "constraints", "sketches"}
    doc.extra = {k: v for k, v in data.items() if k not in known}
    doc.header = Header.from_dict(data.get("header", {}))
    layers = [Layer.from_dict(x) for x in data.get("layers", [])]
    doc.layers = {layer.name: layer for layer in layers}
    doc.layers.setdefault("0", Layer("0"))
    for lt in data.get("linetypes", []):
        lt_obj = Linetype.from_dict(lt)
        doc.linetypes[lt_obj.name] = lt_obj
    for bd in data.get("blocks", []):
        b = BlockDefinition.from_dict(bd)
        doc.blocks[b.name] = b
    for sd in data.get("dimstyles", []):
        st = DimStyle.from_dict(sd)
        doc.dimstyles[st.name] = st
    for gd in data.get("groups", []):
        g = Group.from_dict(gd)
        doc.groups[g.name] = g
    for ld in data.get("layouts", []):
        lo = Layout.from_dict(ld)
        doc.layouts[lo.name] = lo
    from ..core.model.tables import SKETCH_PREFIX, Sketch
    for sd in data.get("sketches", []):
        sk = Sketch.from_dict(sd)
        doc.sketches[sk.name] = sk
    if data.get("constraints"):
        from ..core.constraints.model import constraints_from_list
        doc.constraints = constraints_from_list(data["constraints"])
    doc.entities = {}
    for ed in data.get("entities", []):
        e = entity_from_dict(ed)
        if e.layer not in doc.layers:          # repair dangling references
            doc.layers[e.layer] = Layer(e.layer)
        if e.space.startswith(SKETCH_PREFIX):
            name = e.space[len(SKETCH_PREFIX):]
            doc.sketches.setdefault(name, Sketch(name))
        elif e.space != "*Model" and e.space not in doc.layouts:
            doc.layouts[e.space] = Layout(e.space, order=len(doc.layouts) + 1)
        doc.entities[e.handle] = e
    doc.next_handle = max(int(data.get("next_handle", 1)), max(doc.entities, default=0) + 1)
    if doc.header.current_layer not in doc.layers:
        from dataclasses import replace
        doc.header = replace(doc.header, current_layer="0")
    return doc


def _solid_dicts(data: dict):
    for ed in data.get("entities", []):
        if ed.get("type") == "solid":
            yield ed
    for bd in data.get("blocks", []):
        for ed in bd.get("entities", []):
            if ed.get("type") == "solid":
                yield ed


def _extract_breps(data: dict) -> dict[str, str]:
    """Move each solid's BREP text out of document.json into solids/<n>.brep."""
    out: dict[str, str] = {}
    for i, ed in enumerate(_solid_dicts(data), 1):
        text = ed.get("shape")
        if isinstance(text, str):
            name = f"solids/{ed.get('handle', 0)}_{i}.brep"
            out[name] = text
            ed["shape"] = {"file": name}
    return out


def _restore_breps(data: dict, z, names: set) -> None:
    for ed in _solid_dicts(data):
        ref = ed.get("shape")
        if isinstance(ref, dict) and ref.get("file") in names:
            ed["shape"] = z.read(ref["file"]).decode("ascii", errors="replace")
        elif isinstance(ref, dict):
            ed["type"] = "solid_missing"          # keeps the record; shown as an unknown object
            ed["note"] = "3D data file missing from the drawing"


def save(doc: Document, path: str, thumbnail_png: bytes | None = None) -> None:
    """Write atomically: a temp file in the same folder, then rename over the target."""
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    created = doc.extra.get("_created") if isinstance(doc.extra.get("_created"), str) else now
    manifest = {
        "format": FORMAT_NAME,
        "format_version": _version_str(FORMAT_VERSION),
        "app": APP_NAME,
        "app_version": __version__,
        "created": created,
        "modified": now,
    }
    data = document_to_dict(doc)
    data.pop("_created", None)
    breps = _extract_breps(data)
    manifest_extra = getattr(doc, "manifest_extra", {})
    manifest = {**manifest_extra, **manifest}

    folder = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".~", suffix=".cadz.tmp", dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
            z.writestr("document.json", json.dumps(data, separators=(",", ":")))
            if thumbnail_png:
                z.writestr("thumbnail.png", thumbnail_png)
            for name, text in breps.items():
                z.writestr(name, text)
            for name, blob in getattr(doc, "extra_members", {}).items():
                z.writestr(name, blob)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    doc.extra["_created"] = created


def load(path: str) -> tuple[Document, list[str]]:
    """Open a .cadz file. Returns (document, warnings)."""
    warnings: list[str] = []
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise FileFormatError("This isn't a valid .cadz file (not a ZIP archive)") from exc
    with z:
        names = set(z.namelist())
        if "manifest.json" not in names or "document.json" not in names:
            raise FileFormatError("This .cadz file is missing manifest.json or document.json")
        try:
            manifest = json.loads(z.read("manifest.json"))
            data = json.loads(z.read("document.json"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise FileFormatError(f"The file is damaged: {exc}") from exc
        if manifest.get("format") != FORMAT_NAME:
            raise FileFormatError("Not a CAD: Calling All Dumbies drawing")
        version = _parse_version(str(manifest.get("format_version", "1.0.0")))
        if version[0] > FORMAT_VERSION[0]:
            raise FileFormatError(
                f"This drawing was saved by a newer version (file format {_version_str(version)}). "
                "Please update the program to open it.")
        if version > FORMAT_VERSION:
            warnings.append(
                f"This drawing comes from a newer version (format {_version_str(version)}). "
                "Features this version doesn't know are kept and saved back unchanged.")
        data = _migrate(data, version)
        _restore_breps(data, z, names)
        extra_members = {n: z.read(n) for n in names - KNOWN_MEMBERS}
    doc = document_from_dict(data)
    doc.extra["_created"] = manifest.get("created")
    doc.manifest_extra = {k: v for k, v in manifest.items()
                          if k not in {"format", "format_version", "app", "app_version", "created", "modified"}}
    doc.extra_members = extra_members
    unknown = sum(1 for e in doc.entities.values() if e.TYPE == "unknown")
    if unknown:
        warnings.append(f"{unknown} object(s) of a type this version doesn't know were kept but can't be shown.")
    doc.path = path
    doc.mark_saved()
    return doc, warnings
