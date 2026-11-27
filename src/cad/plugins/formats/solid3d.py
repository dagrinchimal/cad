"""3D file formats.

Exact solids:  STEP (.step/.stp, with colors and names) and IGES (.igs/.iges) — import and export.
Meshes:        STL (import and export), glTF binary (.glb), OBJ (.obj + .mtl), 3MF — export.
Only solids are written; 2D objects stay behind (the report says so).
"""
from __future__ import annotations

import json
import os
import struct
import tempfile
import zipfile
from xml.sax.saxutils import escape

import numpy as np

from ...core.model import MODEL_SPACE, Document, Solid, color_to_rgb
from ..base import Capabilities, FormatPlugin, Option, PluginError, Report

QUALITY = {"coarse": 4e-3, "normal": 1e-3, "fine": 2.5e-4}     # deflection as a fraction of the part size


def _quiet_occt() -> None:
    """OpenCascade's readers/writers print progress to the console; keep only failures."""
    try:
        from OCP.Message import Message, Message_Gravity
        printers = Message.DefaultMessenger_s().Printers()
        for i in range(1, printers.Length() + 1):
            printers.Value(i).SetTraceLevel(Message_Gravity.Message_Fail)
    except Exception:
        pass


_quiet_occt()


def _solids(doc: Document) -> list[Solid]:
    return [e for e in doc.entities.values() if isinstance(e, Solid) and e.space == MODEL_SPACE and doc.is_visible(e)]


def _need_solids(doc: Document, report: Report) -> list[Solid]:
    sols = _solids(doc)
    if not sols:
        raise PluginError("This drawing has no 3D solids to export. Make some with EXTRUDE, BOX, etc., "
                          "or export to DXF/PDF for 2D drawings.")
    others = sum(1 for e in doc.entities.values() if not isinstance(e, Solid))
    if others:
        report.warn(f"{others} 2D object(s) were left out: this format holds only 3D solids.")
    return sols


def _rgb01(doc: Document, e) -> tuple[float, float, float]:
    r, g, b = color_to_rgb(doc.effective_color(e), dark_background=False)
    if (r, g, b) in ((0, 0, 0), (255, 255, 255)):
        return (0.75, 0.75, 0.78)                # color 7 (black/white): a neutral grey part
    return (r / 255.0, g / 255.0, b / 255.0)


def _name(e: Solid) -> str:
    return e.name or f"Solid{e.handle}"


class Solid3DPlugin(FormatPlugin):
    capabilities = frozenset({Capabilities.SOLIDS_3D, Capabilities.COLORS})
    builtin = True

    def available(self):
        try:
            import OCP  # noqa: F401
        except ImportError:
            return False, "The 3D kernel (OpenCascade) isn't installed."
        return True, ""

    def losses(self, doc: Document) -> list[str]:
        out = []
        n2d = sum(1 for e in doc.entities.values() if not isinstance(e, Solid))
        if n2d:
            out.append(f"2D objects (lines, text, dimensions, layouts…) — {n2d} in this drawing; only solids are written")
        if Capabilities.COLORS not in self.capabilities and any(isinstance(e, Solid) for e in doc.entities.values()):
            out.append("colors")
        return out


# ====================================================================== mesh helpers
def _mesh_data(doc: Document, sols, quality: str):
    """[(name, rgb, vertices (n,3), normals (n,3), triangles (m,3))] in mm."""
    from ...core import solids as S
    out = []
    for e in sols:
        defl = max(S.diagonal(e.shape) * QUALITY.get(quality, 1e-3), 1e-4)
        m = S.mesh(e.shape, deflection=defl) if quality != "normal" else S.mesh(e.shape)
        if not len(m.triangles):
            continue
        out.append((_name(e), _rgb01(doc, e), m.vertices.astype(np.float64), m.normals.astype(np.float64),
                    m.triangles.astype(np.int64)))
    if not out:
        raise PluginError("The solids couldn't be turned into triangles.")
    return out


def _quality_option():
    return Option("quality", "Smoothness of curved faces", "choice", "normal",
                  (("coarse", "Coarse (small file)"), ("normal", "Normal"), ("fine", "Fine (large file)")),
                  help="How closely the triangles follow round surfaces.")


# ====================================================================== STEP / IGES
class StepPlugin(Solid3DPlugin):
    id = "step"
    name = "STEP 3D model"
    extensions = (".step", ".stp")
    can_import = True
    can_export = True
    description = "The standard for exchanging exact 3D parts with other CAD programs (SolidWorks, Fusion, FreeCAD…)."

    def export_options(self, doc=None):
        return [Option("schema", "STEP version", "choice", "AP214",
                       (("AP214", "AP214 (colors, most compatible)"), ("AP203", "AP203 (older programs)"),
                        ("AP242", "AP242 (newest)")))]

    def export(self, doc, path, options, report):
        sols = _need_solids(doc, report)
        o = self.checked_options("export", options, doc)
        from OCP.Interface import Interface_Static
        Interface_Static.SetCVal_s("write.step.unit", "MM")
        Interface_Static.SetCVal_s("write.step.schema", {"AP203": "AP203", "AP214": "AP214IS",
                                                         "AP242": "AP242DIS"}[o["schema"]])
        try:
            _write_step_xcaf(doc, sols, path)
            report.info("Colors and names were written.")
        except Exception as exc:          # XCAF missing or failed: exact shapes without colors
            report.warn(f"Colors couldn't be written ({exc}); shapes only.")
            from OCP.IFSelect import IFSelect_RetDone
            from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
            w = STEPControl_Writer()
            for e in sols:
                w.Transfer(e.shape, STEPControl_AsIs)
            if w.Write(path) != IFSelect_RetDone:
                raise PluginError("The STEP file couldn't be written.") from exc
        report.count("SOLID", len(sols))

    def import_(self, path, options, report):
        shapes = _read_step(path, report)
        return _document_from_shapes(shapes, report, "STEP")


def _write_step_xcaf(doc, sols, path):
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Quantity import Quantity_Color, Quantity_TOC_sRGB
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_DocumentTool
    xdoc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    XCAFApp_Application.GetApplication_s().InitDocument(xdoc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(xdoc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(xdoc.Main())
    for e in sols:
        label = st.AddShape(e.shape, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(_name(e)))
        r, g, b = _rgb01(doc, e)
        ct.SetColor(label, Quantity_Color(r, g, b, Quantity_TOC_sRGB), XCAFDoc_ColorSurf)
    w = STEPCAFControl_Writer()
    w.SetColorMode(True)
    w.SetNameMode(True)
    if not w.Transfer(xdoc, STEPControl_AsIs):
        raise RuntimeError("transfer failed")
    if w.Write(path) != IFSelect_RetDone:
        raise RuntimeError("write failed")


def _read_step(path, report):
    """[(shape, name, rgb or None)]"""
    try:
        return _read_step_xcaf(path)
    except Exception as exc:
        report.warn(f"Colors and names couldn't be read ({exc}).")
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader
    r = STEPControl_Reader()
    if r.ReadFile(path) != IFSelect_RetDone:
        raise PluginError("This doesn't look like a STEP file, or it's damaged.")
    r.TransferRoots()
    return [(r.OneShape(), "", None)]


def _read_step_xcaf(path):
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Quantity import Quantity_Color, Quantity_TOC_sRGB
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    try:
        from OCP.TDF import TDF_LabelSequence
    except ImportError:                        # OCP 8 moved collections
        from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_ColorGen, XCAFDoc_ColorSurf, XCAFDoc_DocumentTool
    xdoc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    XCAFApp_Application.GetApplication_s().InitDocument(xdoc)
    rd = STEPCAFControl_Reader()
    rd.SetColorMode(True)
    rd.SetNameMode(True)
    if rd.ReadFile(path) != IFSelect_RetDone:
        raise PluginError("This doesn't look like a STEP file, or it's damaged.")
    if not rd.Transfer(xdoc):
        raise RuntimeError("transfer failed")
    st = XCAFDoc_DocumentTool.ShapeTool_s(xdoc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(xdoc.Main())
    labels = TDF_LabelSequence()
    st.GetFreeShapes(labels)
    out = []

    def color_of(label, shape):
        c = Quantity_Color()
        for kind in (XCAFDoc_ColorSurf, XCAFDoc_ColorGen):
            by_label = getattr(ct, "GetColor_s", None) or ct.GetColor
            try:
                found = by_label(label, kind, c)
            except TypeError:
                found = False
            if found or ct.GetColor(shape, kind, c):
                rgb = c.Values(Quantity_TOC_sRGB)
                return tuple(float(v) for v in rgb)
        return None

    def name_of(label):
        attr = TDataStd_Name()
        if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
            return attr.Get().ToExtString()
        return ""

    def walk(label, inherited_color=None):
        shape = st.GetShape_s(label)
        if st.IsAssembly_s(label):
            comps = TDF_LabelSequence()
            st.GetComponents_s(label, comps, False)
            col = color_of(label, shape) or inherited_color
            for i in range(1, comps.Length() + 1):
                walk(comps.Value(i), col)
            return
        if st.IsReference_s(label):
            ref = label.__class__()
            st.GetReferredShape_s(label, ref)
            col = color_of(label, shape) or color_of(ref, st.GetShape_s(ref)) or inherited_color
            out.append((shape, name_of(ref) or name_of(label), col))   # shape carries the placement
            return
        out.append((shape, name_of(label), color_of(label, shape) or inherited_color))

    for i in range(1, labels.Length() + 1):
        walk(labels.Value(i))
    if not out:
        raise RuntimeError("no shapes")
    return out


def _document_from_shapes(shapes, report, what: str) -> Document:
    from ...core import solids as S
    doc = Document()
    with doc.transaction(f"Import {what}"):
        n = 0
        for shape, name, rgb in shapes:
            parts = S.solids_of(shape)
            if not parts:
                fixed = _sew_to_solid(shape)
                parts = S.solids_of(fixed) if fixed is not None else []
                if parts:
                    report.info("Open surfaces were stitched into solids.")
                elif fixed is not None and S.faces(fixed):
                    report.warn("Some surfaces aren't closed solids; they were brought in as thin shells "
                                "(you can look at them but booleans may fail).")
                    parts = [fixed]
            for i, p in enumerate(parts):
                color = 256 if rgb is None else _rgb_color(rgb)
                nm = name if len(parts) == 1 else (f"{name} {i + 1}" if name else "")
                doc.add(Solid(shape=p, name=nm or "", color=color))
                n += 1
        if not n:
            raise PluginError(f"No solids were found in this {what} file.")
        report.count("SOLID", n)
    doc.mark_saved()
    return doc


def _rgb_color(rgb):
    r, g, b = (int(round(v * 255)) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _sew_to_solid(shape):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from ...core import solids as S
    if not S.faces(shape):
        return None
    sew = BRepBuilderAPI_Sewing(1e-3)
    sew.Add(shape)
    sew.Perform()
    sewn = sew.SewedShape()
    ex = TopExp_Explorer(sewn, TopAbs_SHELL)
    made = []
    while ex.More():
        try:
            ms = BRepBuilderAPI_MakeSolid(TopoDS.Shell(ex.Current()))
            if ms.IsDone():
                fix = ShapeFix_Solid(ms.Solid())
                fix.Perform()
                sol = fix.Solid()
                if S.mass_properties(sol)["volume"] < 0:
                    sol.Reverse()
                made.append(sol)
        except Exception:
            pass
        ex.Next()
    if not made:
        return sewn
    return made[0] if len(made) == 1 else S.compound(made)


class IgesPlugin(Solid3DPlugin):
    id = "iges"
    name = "IGES 3D model"
    extensions = (".igs", ".iges")
    can_import = True
    can_export = True
    capabilities = frozenset({Capabilities.SOLIDS_3D})
    description = "An older exchange format for 3D shapes, still used by some CAM and CAD programs."

    def export(self, doc, path, options, report):
        sols = _need_solids(doc, report)
        from OCP.IGESControl import IGESControl_Controller, IGESControl_Writer
        IGESControl_Controller.Init_s()
        w = IGESControl_Writer("MM", 1)       # 1 = BRep solids (not just surfaces)
        for e in sols:
            w.AddShape(e.shape)
        w.ComputeModel()
        if not w.Write(path):
            raise PluginError("The IGES file couldn't be written.")
        report.count("SOLID", len(sols))
        report.warn("IGES has no colors or names.") if any(e.color != 256 for e in sols) else None

    def import_(self, path, options, report):
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.IGESControl import IGESControl_Reader
        r = IGESControl_Reader()
        if r.ReadFile(path) != IFSelect_RetDone:
            raise PluginError("This doesn't look like an IGES file, or it's damaged.")
        r.TransferRoots()
        return _document_from_shapes([(r.OneShape(), "", None)], report, "IGES")


# ====================================================================== STL
class StlPlugin(Solid3DPlugin):
    id = "stl"
    name = "STL mesh (3D printing)"
    extensions = (".stl",)
    can_import = True
    can_export = True
    capabilities = frozenset({Capabilities.SOLIDS_3D})
    description = "Triangles for 3D printers and slicers. Curved faces become flat triangles; no colors."

    def export_options(self, doc=None):
        return [_quality_option(),
                Option("binary", "Binary file", "bool", True, help="Smaller and faster. Turn off for a text file."),
                Option("one_file", "All solids in one file", "bool", True)]

    def export(self, doc, path, options, report):
        o = self.checked_options("export", options, doc)
        meshes = _mesh_data(doc, _need_solids(doc, report), o["quality"])
        if o["one_file"] or len(meshes) == 1:
            _write_stl(path, meshes, o["binary"])
        else:
            base, ext = os.path.splitext(path)
            for i, m in enumerate(meshes, 1):
                _write_stl(f"{base}_{i}{ext}", [m], o["binary"])
            report.info(f"Wrote {len(meshes)} files: {os.path.basename(base)}_1{ext} …")
        report.count("TRIANGLE", sum(len(m[4]) for m in meshes))

    def import_(self, path, options, report):
        tris = read_stl(path)
        if not len(tris):
            raise PluginError("This STL file has no triangles.")
        shape = _shape_from_triangles(tris)
        report.info(f"{len(tris)} triangles. Imported meshes are made of flat faces: "
                    "booleans work, but fillets on them won't.")
        return _document_from_shapes([(shape, os.path.splitext(os.path.basename(path))[0], None)], report, "STL")


def _write_stl(path, meshes, binary: bool) -> None:
    tris = np.concatenate([v[t] for _n, _c, v, _nn, t in meshes])       # (m,3,3)
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(n, axis=1)
    n = np.where(ln[:, None] > 0, n / np.where(ln > 0, ln, 1)[:, None], 0)
    if binary:
        rec = np.zeros(len(tris), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        rec["n"], rec["v"] = n, tris
        with open(path, "wb") as f:
            f.write(b"CAD: Calling All Dumbies STL, units mm".ljust(80, b" "))
            f.write(struct.pack("<I", len(tris)))
            f.write(rec.tobytes())
    else:
        with open(path, "w", encoding="ascii") as f:
            f.write("solid cad\n")
            for nn, t in zip(n, tris):
                f.write(f"  facet normal {nn[0]:.6e} {nn[1]:.6e} {nn[2]:.6e}\n    outer loop\n")
                for p in t:
                    f.write(f"      vertex {p[0]:.6e} {p[1]:.6e} {p[2]:.6e}\n")
                f.write("    endloop\n  endfacet\n")
            f.write("endsolid cad\n")


def read_stl(path) -> np.ndarray:
    """(m,3,3) triangles from a binary or text STL."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) >= 84:
        count = struct.unpack("<I", data[80:84])[0]
        if 84 + count * 50 == len(data):
            rec = np.frombuffer(data, dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")],
                                count=count, offset=84)
            return rec["v"].astype(np.float64)
    text = data.decode("ascii", errors="replace")
    if "facet" not in text:
        raise PluginError("This doesn't look like an STL file.")
    vals = [line.split()[1:4] for line in text.splitlines() if line.strip().startswith("vertex")]
    a = np.array(vals, float)
    return a[: len(a) // 3 * 3].reshape(-1, 3, 3)


def _shape_from_triangles(tris: np.ndarray):
    """A shell (then a solid, if closed) of flat triangular faces, with shared vertices merged."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
    from OCP.TopoDS import TopoDS_Compound
    from ...core.solids import P
    if len(tris) > 200_000:
        raise PluginError("This mesh has more than 200,000 triangles; that's too many to edit here.")
    comp = TopoDS_Compound()
    bld = BRep_Builder()
    bld.MakeCompound(comp)
    for t in tris:
        a, b, c = (tuple(float(x) for x in p) for p in t)
        if np.linalg.norm(np.cross(np.subtract(b, a), np.subtract(c, a))) < 1e-12:
            continue
        poly = BRepBuilderAPI_MakePolygon(P(a), P(b), P(c), True)
        f = BRepBuilderAPI_MakeFace(poly.Wire(), True)
        if f.IsDone():
            bld.Add(comp, f.Face())
    return comp


# ====================================================================== glTF / OBJ / 3MF
class GltfPlugin(Solid3DPlugin):
    id = "gltf"
    name = "glTF binary (web, AR, Blender)"
    extensions = (".glb",)
    can_export = True
    description = "A compact 3D model for web viewers, AR, Windows 3D Viewer and Blender. Keeps colors."

    def export_options(self, doc=None):
        return [_quality_option()]

    def export(self, doc, path, options, report):
        o = self.checked_options("export", options, doc)
        meshes = _mesh_data(doc, _need_solids(doc, report), o["quality"])
        write_glb(path, meshes)
        report.count("MESH", len(meshes))
        report.info("glTF is in meters: the model was scaled from mm so it shows at real size.")


def write_glb(path, meshes) -> None:
    bin_parts, views, accessors, gl_meshes, materials, nodes = [], [], [], [], [], []
    offset = 0

    def add_view(arr: np.ndarray, target: int):
        nonlocal offset
        b = arr.tobytes()
        pad = (-len(b)) % 4
        bin_parts.append(b + b"\0" * pad)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(b), "target": target})
        offset += len(b) + pad
        return len(views) - 1

    for i, (name, rgb, v, n, t) in enumerate(meshes):
        # glTF: Y up, meters. Our model: Z up, mm.
        pos = (v[:, [0, 2, 1]] * np.array([1, 1, -1]) / 1000.0).astype("<f4")
        nrm = (n[:, [0, 2, 1]] * np.array([1, 1, -1])).astype("<f4")
        ln = np.linalg.norm(nrm, axis=1)
        nrm = np.where(ln[:, None] > 1e-9, nrm / np.where(ln > 1e-9, ln, 1)[:, None], np.array([0, 1, 0], "<f4"))
        nrm = nrm.astype("<f4")
        idx = t.astype("<u4").reshape(-1)
        pv = add_view(pos, 34962)
        accessors.append({"bufferView": pv, "componentType": 5126, "count": len(pos), "type": "VEC3",
                          "min": pos.min(axis=0).tolist(), "max": pos.max(axis=0).tolist()})
        nv = add_view(nrm, 34962)
        accessors.append({"bufferView": nv, "componentType": 5126, "count": len(nrm), "type": "VEC3"})
        iv = add_view(idx, 34963)
        accessors.append({"bufferView": iv, "componentType": 5125, "count": len(idx), "type": "SCALAR"})
        materials.append({"name": f"{name} color", "pbrMetallicRoughness": {
            "baseColorFactor": [*rgb, 1.0], "metallicFactor": 0.1, "roughnessFactor": 0.6}})
        gl_meshes.append({"name": name, "primitives": [{"attributes": {"POSITION": len(accessors) - 3,
                                                                       "NORMAL": len(accessors) - 2},
                                                        "indices": len(accessors) - 1, "material": i}]})
        nodes.append({"name": name, "mesh": i})
    binary = b"".join(bin_parts)
    gltf = {"asset": {"version": "2.0", "generator": "CAD: Calling All Dumbies"},
            "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": gl_meshes,
            "materials": materials, "accessors": accessors, "bufferViews": views,
            "buffers": [{"byteLength": len(binary)}]}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(binary), 0x004E4942) + binary)


class ObjPlugin(Solid3DPlugin):
    id = "obj"
    name = "Wavefront OBJ"
    extensions = (".obj",)
    can_export = True
    description = "A simple mesh format nearly every 3D program opens. Colors go in a .mtl file next to it."

    def export_options(self, doc=None):
        return [_quality_option()]

    def export(self, doc, path, options, report):
        o = self.checked_options("export", options, doc)
        meshes = _mesh_data(doc, _need_solids(doc, report), o["quality"])
        mtl = os.path.splitext(path)[0] + ".mtl"
        with open(mtl, "w", encoding="utf-8") as f:
            for i, (_name_, rgb, *_r) in enumerate(meshes):
                f.write(f"newmtl color{i}\nKd {rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f}\nKa 0 0 0\nKs 0.1 0.1 0.1\n\n")
        base = 1
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# CAD: Calling All Dumbies - units mm\nmtllib {os.path.basename(mtl)}\n")
            for i, (name, _rgb, v, n, t) in enumerate(meshes):
                f.write(f"o {name.replace(' ', '_')}\nusemtl color{i}\n")
                f.write("".join(f"v {x:.6f} {y:.6f} {z:.6f}\n" for x, y, z in v))
                f.write("".join(f"vn {x:.5f} {y:.5f} {z:.5f}\n" for x, y, z in n))
                f.write("".join(f"f {a + base}//{a + base} {b + base}//{b + base} {c + base}//{c + base}\n"
                                for a, b, c in t))
                base += len(v)
        report.count("MESH", len(meshes))
        report.info(f"Colors are in {os.path.basename(mtl)}; keep it next to the .obj.")


class ThreeMfPlugin(Solid3DPlugin):
    id = "3mf"
    name = "3MF (3D printing)"
    extensions = (".3mf",)
    can_export = True
    description = "The modern 3D printing format (PrusaSlicer, Cura, Bambu Studio). Keeps units and colors."

    def export_options(self, doc=None):
        return [_quality_option()]

    def export(self, doc, path, options, report):
        o = self.checked_options("export", options, doc)
        meshes = _mesh_data(doc, _need_solids(doc, report), o["quality"])
        model = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<model unit="millimeter" xml:lang="en-US" '
            'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">',
            '<metadata name="Application">CAD: Calling All Dumbies</metadata>', "<resources>",
            '<basematerials id="1">' + "".join(
                f'<base name="{escape(nm)}" displaycolor="#{int(c[0] * 255):02X}{int(c[1] * 255):02X}'
                f'{int(c[2] * 255):02X}" />' for nm, c, *_r in meshes) + "</basematerials>"]
        for i, (name, _c, v, _n, t) in enumerate(meshes):
            # merge duplicate vertices so slicers see one closed (manifold) mesh
            vq = np.round(v, 6)
            uniq, inv = np.unique(vq, axis=0, return_inverse=True)
            tt = inv.reshape(-1)[t]
            keep = (tt[:, 0] != tt[:, 1]) & (tt[:, 1] != tt[:, 2]) & (tt[:, 0] != tt[:, 2])
            tt = tt[keep]
            model.append(f'<object id="{i + 2}" name="{escape(name)}" type="model" pid="1" pindex="{i}"><mesh><vertices>')
            model.append("".join(f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}" />' for x, y, z in uniq))
            model.append("</vertices><triangles>")
            model.append("".join(f'<triangle v1="{a}" v2="{b}" v3="{c}" />' for a, b, c in tt))
            model.append("</triangles></mesh></object>")
        model.append("</resources><build>")
        model += [f'<item objectid="{i + 2}" />' for i in range(len(meshes))]
        model.append("</build></model>")
        ctypes = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
                  'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
                  'relationships+xml" /><Default Extension="model" ContentType="application/vnd.ms-package.'
                  '3dmanufacturing-3dmodel+xml" /></Types>')
        rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                'package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" '
                'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" /></Relationships>')
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ctypes)
            z.writestr("_rels/.rels", rels)
            z.writestr("3D/3dmodel.model", "".join(model))
        report.count("MESH", len(meshes))


PLUGINS = [StepPlugin(), IgesPlugin(), StlPlugin(), GltfPlugin(), ObjPlugin(), ThreeMfPlugin()]
_ = tempfile
