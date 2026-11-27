"""3D solids on OpenCascade (OCP). Everything here works on TopoDS_Shape objects; nothing uses Qt.

Planes map the program's 2D drawing coordinates (mm) to 3D: model space is the XY plane at z=0, and
a sketch has its own plane. Profiles (closed 2D outlines) become faces on a plane; faces become solids
by extrude, revolve, sweep or loft; solids combine with booleans and are refined with fillets,
chamfers, shells, slices and push/pull. All results are new shapes (entities are immutable).
"""
from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse, BRepAlgoAPI_Section
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Transform,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepLib import BRepLib, BRepLib_ToolTriangulatedShape
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_MakeThickSolid, BRepOffsetAPI_ThruSections
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism,
    BRepPrimAPI_MakeRevol, BRepPrimAPI_MakeSphere, BRepPrimAPI_MakeTorus,
)
from OCP.BRepTools import BRepTools
from OCP.Bnd import Bnd_Box
from OCP.GC import GC_MakeArcOfCircle, GC_MakeSegment
from OCP.GCPnts import GCPnts_TangentialDeflection
from OCP.Geom import Geom_BSplineCurve
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line, GeomAbs_Plane
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Ax1, gp_Ax2, gp_Ax3, gp_Circ, gp_Dir, gp_Elips, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
try:                                      # OCP 8 moved OCCT's arrays into OCP.collections
    from OCP.collections import Array1_double as RealArray, Array1_gp_Pnt as PntArray, Array1_int as IntArray
except ImportError:                       # pragma: no cover - OCP 7.x
    from OCP.TColStd import TColStd_Array1OfInteger as IntArray, TColStd_Array1OfReal as RealArray
    from OCP.TColgp import TColgp_Array1OfPnt as PntArray
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID, TopAbs_VERTEX, TopAbs_WIRE
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
try:
    from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as ShapeMap
    from OCP.collections import List_TopoDS_Shape as ShapeList
except ImportError:                       # pragma: no cover - OCP 7.x
    from OCP.TopTools import TopTools_IndexedMapOfShape as ShapeMap, TopTools_ListOfShape as ShapeList
from OCP.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Shape

Vec3 = tuple[float, float, float]


def _cast(name: str):
    """TopoDS.Face_s (OCP 7) or TopoDS.Face (OCP 8)."""
    return getattr(TopoDS, name + "_s", None) or getattr(TopoDS, name)


as_face, as_edge, as_wire, as_vertex = (_cast(n) for n in ("Face", "Edge", "Wire", "Vertex"))
TOL = 1e-6


class SolidError(ValueError):
    """A modeling operation failed. The message is shown to the user."""


# ====================================================================== planes
@dataclass(frozen=True, slots=True)
class Plane:
    """A drawing plane: 2D (x, y) maps to origin + x*xdir + y*ydir."""
    origin: Vec3 = (0.0, 0.0, 0.0)
    xdir: Vec3 = (1.0, 0.0, 0.0)
    normal: Vec3 = (0.0, 0.0, 1.0)

    @property
    def ydir(self) -> Vec3:
        n, x = np.array(self.normal), np.array(self.xdir)
        return tuple(float(v) for v in np.cross(n, x))

    def to_world(self, x: float, y: float, z: float = 0.0) -> Vec3:
        o, xd, yd, n = (np.array(v) for v in (self.origin, self.xdir, self.ydir, self.normal))
        return tuple(float(v) for v in o + x * xd + y * yd + z * n)

    def to_local(self, p: Vec3) -> Vec3:
        d = np.array(p) - np.array(self.origin)
        return (float(d @ np.array(self.xdir)), float(d @ np.array(self.ydir)), float(d @ np.array(self.normal)))

    def matrix(self) -> np.ndarray:
        """4x4 local -> world."""
        m = np.eye(4)
        m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = self.xdir, self.ydir, self.normal, self.origin
        return m

    def ax3(self) -> gp_Ax3:
        return gp_Ax3(gp_Pnt(*self.origin), gp_Dir(*self.normal), gp_Dir(*self.xdir))

    def offset(self, d: float) -> "Plane":
        return Plane(tuple(float(v) for v in np.array(self.origin) + d * np.array(self.normal)), self.xdir, self.normal)

    def to_dict(self) -> dict:
        return {"origin": list(self.origin), "xdir": list(self.xdir), "normal": list(self.normal)}

    @classmethod
    def from_dict(cls, d: dict) -> "Plane":
        return cls(tuple(d["origin"]), tuple(d["xdir"]), tuple(d["normal"]))

    @classmethod
    def make(cls, origin, normal, xdir=None) -> "Plane":
        n = np.array(normal, dtype=float)
        n /= np.linalg.norm(n)
        if xdir is None:
            ref = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
            if abs(n[2]) < 0.9 and abs(n[0]) >= 0.9:
                ref = np.array([0, 1.0, 0])
            xd = ref - (ref @ n) * n
        else:
            xd = np.array(xdir, dtype=float) - (np.array(xdir) @ n) * n
        xd /= np.linalg.norm(xd)
        return cls(tuple(float(v) for v in origin), tuple(float(v) for v in xd), tuple(float(v) for v in n))


XY = Plane()
XZ = Plane((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0))     # front: x right, z up
YZ = Plane((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))      # right side: y right, z up
STANDARD_PLANES = {"XY": XY, "XZ": XZ, "YZ": YZ}


def P(p) -> gp_Pnt:
    return gp_Pnt(float(p[0]), float(p[1]), float(p[2]))


def V(v) -> gp_Vec:
    return gp_Vec(float(v[0]), float(v[1]), float(v[2]))


# ====================================================================== shapes in and out
def to_brep(shape: TopoDS_Shape) -> str:
    fd, path = tempfile.mkstemp(suffix=".brep")
    os.close(fd)
    try:
        BRepTools.Write_s(shape, path)
        with open(path, encoding="ascii", errors="replace") as fh:
            return fh.read()
    finally:
        os.unlink(path)


def from_brep(text: str) -> TopoDS_Shape:
    fd, path = tempfile.mkstemp(suffix=".brep")
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(text)
    try:
        shape = TopoDS_Shape()
        if not BRepTools.Read_s(shape, path, BRep_Builder()):
            raise SolidError("The 3D data in the file is damaged.")
        return shape
    finally:
        os.unlink(path)


def is_valid(shape: TopoDS_Shape) -> bool:
    return BRepCheck_Analyzer(shape).IsValid()


def _check(shape: TopoDS_Shape, what: str) -> TopoDS_Shape:
    if shape is None or shape.IsNull():
        raise SolidError(f"{what} didn't produce a shape.")
    return shape


def clean(shape: TopoDS_Shape) -> TopoDS_Shape:
    """Merge faces and edges that lie on the same surface after booleans."""
    try:
        u = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
        u.Build()
        out = u.Shape()
        return out if not out.IsNull() else shape
    except Exception:                         # noqa: BLE001
        return shape


def solids_of(shape: TopoDS_Shape) -> list[TopoDS_Shape]:
    out, ex = [], TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        out.append(ex.Current())
        ex.Next()
    return out


def subshapes(shape: TopoDS_Shape, kind) -> list[TopoDS_Shape]:
    """Faces / edges / vertices with stable 0-based indices (TopExp map order)."""
    m = ShapeMap()
    TopExp.MapShapes_s(shape, kind, m)
    return [m.FindKey(i) for i in range(1, m.Extent() + 1)]


def faces(shape) -> list[TopoDS_Shape]:
    return [as_face(f) for f in subshapes(shape, TopAbs_FACE)]


def edges(shape) -> list[TopoDS_Shape]:
    return [as_edge(e) for e in subshapes(shape, TopAbs_EDGE)]


def vertices(shape) -> list[Vec3]:
    out = []
    for v in subshapes(shape, TopAbs_VERTEX):
        p = BRep_Tool.Pnt_s(as_vertex(v))
        out.append((p.X(), p.Y(), p.Z()))
    return out


# ====================================================================== profiles
def _bulge_edge(plane: Plane, a, b, bulge: float):
    pa, pb = P(plane.to_world(*a)), P(plane.to_world(*b))
    if abs(bulge) < 1e-12:
        return BRepBuilderAPI_MakeEdge(GC_MakeSegment(pa, pb).Value()).Edge()
    # arc through its midpoint
    dx, dy = b[0] - a[0], b[1] - a[1]
    chord = math.hypot(dx, dy)
    sagitta = bulge * chord / 2
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    nx, ny = dy / chord, -dx / chord                    # right-hand normal; positive bulge = counter-clockwise
    pm = P(plane.to_world(mx + nx * sagitta, my + ny * sagitta))
    return BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(pa, pm, pb).Value()).Edge()


def wire_from_loop(plane: Plane, verts, closed: bool = True):
    """A wire from (x, y, bulge) vertices in plane coordinates."""
    mk = BRepBuilderAPI_MakeWire()
    n = len(verts)
    count = n if closed else n - 1
    for i in range(count):
        a, b = verts[i], verts[(i + 1) % n]
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-9:
            continue
        mk.Add(_bulge_edge(plane, a[:2], b[:2], a[2] if len(a) > 2 else 0.0))
    if not mk.IsDone():
        raise SolidError("That outline isn't connected end to end.")
    return mk.Wire()


def wire_from_entity(plane: Plane, e):
    """A closed or open wire from a 2D entity (polyline, circle, ellipse, spline, line, arc)."""
    from .model import Arc, Circle, Ellipse, Line, Polyline, Spline
    if isinstance(e, Polyline):
        return wire_from_loop(plane, e.vertices, e.closed)
    if isinstance(e, Line):
        return wire_from_loop(plane, [(*e.p1, 0.0), (*e.p2, 0.0)], closed=False)
    ax = gp_Ax2(P(plane.to_world(0, 0)), gp_Dir(*plane.normal), gp_Dir(*plane.xdir))
    if isinstance(e, Circle):
        ax.SetLocation(P(plane.to_world(*e.center)))
        return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(ax, e.radius)).Edge()).Wire()
    if isinstance(e, Arc):
        ax.SetLocation(P(plane.to_world(*e.center)))
        edge = BRepBuilderAPI_MakeEdge(gp_Circ(ax, e.radius), e.start_angle,
                                       e.start_angle + ((e.end_angle - e.start_angle) % math.tau or math.tau)).Edge()
        return BRepBuilderAPI_MakeWire(edge).Wire()
    if isinstance(e, Ellipse):
        major = math.hypot(*e.major)
        ang = math.atan2(e.major[1], e.major[0])
        xd = np.array(plane.xdir) * math.cos(ang) + np.array(plane.ydir) * math.sin(ang)
        ax2 = gp_Ax2(P(plane.to_world(*e.center)), gp_Dir(*plane.normal), gp_Dir(*xd))
        el = gp_Elips(ax2, major, major * e.ratio)
        full = abs((e.end_param - e.start_param) % math.tau) < 1e-9
        edge = (BRepBuilderAPI_MakeEdge(el).Edge() if full
                else BRepBuilderAPI_MakeEdge(el, e.start_param, e.end_param).Edge())
        return BRepBuilderAPI_MakeWire(edge).Wire()
    if isinstance(e, Spline):
        knots, mults = [], []
        for k in e.knots:
            if knots and abs(k - knots[-1]) < 1e-12:
                mults[-1] += 1
            else:
                knots.append(k)
                mults.append(1)
        poles = PntArray(1, len(e.control_points))
        for i, p in enumerate(e.control_points, 1):
            poles.SetValue(i, P(plane.to_world(*p)))
        kk = RealArray(1, len(knots))
        mm = IntArray(1, len(mults))
        for i, (k, m) in enumerate(zip(knots, mults), 1):
            kk.SetValue(i, k)
            mm.SetValue(i, m)
        curve = Geom_BSplineCurve(poles, kk, mm, e.degree)
        return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(curve).Edge()).Wire()
    raise SolidError(f"A {e.TYPE} can't be used as a profile.")


def is_closed_profile(e) -> bool:
    from .model import Circle, Ellipse, Polyline, Spline
    if isinstance(e, (Circle,)):
        return True
    if isinstance(e, Polyline):
        return e.closed or (len(e.vertices) > 2 and math.dist(e.vertices[0][:2], e.vertices[-1][:2]) < 1e-9)
    if isinstance(e, Ellipse):
        return abs((e.end_param - e.start_param) % math.tau) < 1e-9
    if isinstance(e, Spline):
        return e.closed
    return False


def face_from_wires(plane: Plane, outer, holes=()) -> TopoDS_Shape:
    mk = BRepBuilderAPI_MakeFace(gp_Pln(plane.ax3()), outer, True)
    for h in holes:
        h = as_wire(h.Reversed())
        mk.Add(h)
    if not mk.IsDone():
        raise SolidError("That outline doesn't make a flat area (does it cross itself?).")
    face = mk.Face()
    from OCP.ShapeFix import ShapeFix_Face
    fix = ShapeFix_Face(face)
    fix.FixOrientation()
    fix.Perform()
    return fix.Face()


def face_from_loops(plane: Plane, loops) -> TopoDS_Shape:
    """loops[0] is the outline, the rest are holes; each a list of (x, y, bulge)."""
    outer = wire_from_loop(plane, loops[0])
    holes = [wire_from_loop(plane, lp) for lp in loops[1:]]
    return face_from_wires(plane, outer, holes)


def face_from_entity(plane: Plane, e) -> TopoDS_Shape:
    if not is_closed_profile(e):
        raise SolidError("Profiles must be closed (a closed polyline, circle, rectangle, ellipse or closed spline).")
    return face_from_wires(plane, wire_from_entity(plane, e))


def face_normal(face) -> Vec3:
    """Outward normal of a planar (or any) face at its middle."""
    f = as_face(face)
    surf = BRepAdaptor_Surface(f)
    u = (surf.FirstUParameter() + surf.LastUParameter()) / 2
    v = (surf.FirstVParameter() + surf.LastVParameter()) / 2
    if surf.GetType() == GeomAbs_Plane:
        d = surf.Plane().Axis().Direction()
        n = (d.X(), d.Y(), d.Z())
    else:
        p, nv = gp_Pnt(), gp_Vec()
        BRepGProp_Face(f).Normal(u, v, p, nv)
        L = nv.Magnitude() or 1.0
        n = (nv.X() / L, nv.Y() / L, nv.Z() / L)
        return n                        # BRepGProp_Face already accounts for orientation
    if f.Orientation() == TopAbs_REVERSED:
        n = (-n[0], -n[1], -n[2])
    return n


def face_plane(face) -> Plane | None:
    f = as_face(face)
    surf = BRepAdaptor_Surface(f)
    if surf.GetType() != GeomAbs_Plane:
        return None
    pl = surf.Plane()
    n = face_normal(f)
    c = center_of(f)
    x = pl.XAxis().Direction()
    return Plane.make(c, n, (x.X(), x.Y(), x.Z()))


# ====================================================================== making solids
def extrude(face, distance: float, direction: Vec3 | None = None, both: bool = False) -> TopoDS_Shape:
    """Extrude a face along its normal (or `direction`)."""
    if abs(distance) < 1e-9:
        raise SolidError("The height can't be zero.")
    n = np.array(direction if direction is not None else face_normal(face), dtype=float)
    n /= np.linalg.norm(n)
    if both:
        trsf = gp_Trsf()
        trsf.SetTranslation(V(-n * distance / 2))
        face = BRepBuilderAPI_Transform(face, trsf, True).Shape()
    vec = V(n * distance)
    return _check(BRepPrimAPI_MakePrism(face, vec, False, True).Shape(), "Extrude")


def revolve(face, axis_point: Vec3, axis_dir: Vec3, angle: float = math.tau) -> TopoDS_Shape:
    if abs(angle) < 1e-9:
        raise SolidError("The angle can't be zero.")
    ax = gp_Ax1(P(axis_point), gp_Dir(*axis_dir))
    mk = BRepPrimAPI_MakeRevol(face, ax, angle, True) if abs(abs(angle) - math.tau) > 1e-9 \
        else BRepPrimAPI_MakeRevol(face, ax, True)
    shape = _check(mk.Shape(), "Revolve")
    if not is_valid(shape):
        raise SolidError("The profile crosses the axis; move it to one side of the axis.")
    return shape


def sweep(profile_face, path_wire, profile_plane: Plane) -> TopoDS_Shape:
    """Move a profile along a path. The profile is placed at the path's start, square to it."""
    from OCP.BRepAdaptor import BRepAdaptor_CompCurve
    curve = BRepAdaptor_CompCurve(as_wire(path_wire))
    p0, d0 = gp_Pnt(), gp_Vec()
    curve.D1(curve.FirstParameter(), p0, d0)
    # profile centroid -> path start, profile normal -> path tangent
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(profile_face, props)
    c = props.CentreOfMass()
    src = gp_Ax3(c, gp_Dir(*profile_plane.normal), gp_Dir(*profile_plane.xdir))
    t = np.array([d0.X(), d0.Y(), d0.Z()])
    t /= np.linalg.norm(t)
    ref = np.array(profile_plane.xdir)
    xd = ref - (ref @ t) * t
    if np.linalg.norm(xd) < 1e-6:
        xd = np.cross(t, [0, 0, 1.0]) if abs(t[2]) < 0.9 else np.cross(t, [1.0, 0, 0])
    xd /= np.linalg.norm(xd)
    dst = gp_Ax3(p0, gp_Dir(*t), gp_Dir(*xd))
    trsf = gp_Trsf()
    trsf.SetDisplacement(src, dst)
    placed = BRepBuilderAPI_Transform(profile_face, trsf, True).Shape()
    outer = BRepTools.OuterWire_s(as_face(placed))
    from OCP.BRepBuilderAPI import BRepBuilderAPI_RightCorner
    mk = BRepOffsetAPI_MakePipeShell(as_wire(path_wire))
    mk.SetMode(False)                    # corrected Frenet: keeps the profile upright
    mk.SetTransitionMode(BRepBuilderAPI_RightCorner)      # sharp path corners make mitred corners
    mk.Add(outer, False, False)
    mk.Build()
    if not mk.IsDone():
        raise SolidError("The profile can't follow that path (it may turn too tightly for the profile's size).")
    mk.MakeSolid()
    shape = mk.Shape()
    # holes in the profile: sweep each and subtract
    inner = [w for w in subshapes(placed, TopAbs_WIRE) if not w.IsSame(outer)]
    for w in inner:
        hk = BRepOffsetAPI_MakePipeShell(as_wire(path_wire))
        hk.SetMode(False)
        hk.SetTransitionMode(BRepBuilderAPI_RightCorner)
        hk.Add(as_wire(w), False, False)
        hk.Build()
        if hk.IsDone():
            hk.MakeSolid()
            shape = BRepAlgoAPI_Cut(shape, hk.Shape()).Shape()
    return _check(shape, "Sweep")


def loft(wires: list, solid: bool = True, ruled: bool = False) -> TopoDS_Shape:
    if len(wires) < 2:
        raise SolidError("Pick at least two profiles.")
    mk = BRepOffsetAPI_ThruSections(solid, ruled, 1e-6)
    for w in wires:
        mk.AddWire(as_wire(w))
    mk.CheckCompatibility(True)
    mk.Build()
    if not mk.IsDone():
        raise SolidError("Those profiles can't be lofted (try profiles with the same number of sides).")
    return _check(mk.Shape(), "Loft")


def box(p1: Vec3, p2: Vec3) -> TopoDS_Shape:
    lo = [min(a, b) for a, b in zip(p1, p2)]
    hi = [max(a, b) for a, b in zip(p1, p2)]
    if min(h - l for h, l in zip(hi, lo)) < 1e-9:
        raise SolidError("A box needs a length, width and height.")
    return BRepPrimAPI_MakeBox(P(lo), P(hi)).Shape()


def cylinder(center: Vec3, radius: float, height: float) -> TopoDS_Shape:
    ax = gp_Ax2(P(center), gp_Dir(0, 0, 1 if height > 0 else -1))
    return BRepPrimAPI_MakeCylinder(ax, radius, abs(height)).Shape()


def cone(center: Vec3, r1: float, r2: float, height: float) -> TopoDS_Shape:
    ax = gp_Ax2(P(center), gp_Dir(0, 0, 1 if height > 0 else -1))
    return BRepPrimAPI_MakeCone(ax, r1, r2, abs(height)).Shape()


def sphere(center: Vec3, radius: float) -> TopoDS_Shape:
    return BRepPrimAPI_MakeSphere(P(center), radius).Shape()


def torus(center: Vec3, r_major: float, r_minor: float) -> TopoDS_Shape:
    if r_minor >= r_major:
        raise SolidError("The tube radius must be smaller than the torus radius.")
    return BRepPrimAPI_MakeTorus(gp_Ax2(P(center), gp_Dir(0, 0, 1)), r_major, r_minor).Shape()


def wedge(p1: Vec3, dx: float, dy: float, dz: float) -> TopoDS_Shape:
    """A box sloping from full height at x=0 down to the base at x=dx (like AutoCAD WEDGE)."""
    x, y, z = p1
    plane = Plane((x, y, z), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0))        # XZ plane through p1, normal -y
    face = face_from_loops(plane, [[(0, 0, 0), (dx, 0, 0), (0, dz, 0)]])
    return extrude(face, dy, direction=(0, 1, 0))


# ====================================================================== editing solids
def union(a, b) -> TopoDS_Shape:
    return clean(_check(BRepAlgoAPI_Fuse(a, b).Shape(), "Union"))


def subtract(a, b) -> TopoDS_Shape:
    return clean(_check(BRepAlgoAPI_Cut(a, b).Shape(), "Subtract"))


def intersect(a, b) -> TopoDS_Shape:
    out = clean(_check(BRepAlgoAPI_Common(a, b).Shape(), "Intersect"))
    if not solids_of(out):
        raise SolidError("Those solids don't overlap.")
    return out


def fillet(shape, edge_list, radius: float) -> TopoDS_Shape:
    if radius <= 0:
        raise SolidError("The radius must be greater than zero.")
    mk = BRepFilletAPI_MakeFillet(shape)
    for e in edge_list:
        mk.Add(radius, as_edge(e))
    try:
        mk.Build()
        ok = mk.IsDone()
    except Exception:                       # noqa: BLE001 - OCCT throws on impossible fillets
        ok = False
    if not ok:
        raise SolidError("That fillet doesn't fit (the radius may be too big for the faces next to it).")
    return mk.Shape()


def chamfer(shape, edge_list, distance: float) -> TopoDS_Shape:
    if distance <= 0:
        raise SolidError("The distance must be greater than zero.")
    mk = BRepFilletAPI_MakeChamfer(shape)
    for e in edge_list:
        mk.Add(distance, as_edge(e))
    try:
        mk.Build()
        ok = mk.IsDone()
    except Exception:                       # noqa: BLE001
        ok = False
    if not ok:
        raise SolidError("That chamfer doesn't fit (the distance may be too big).")
    return mk.Shape()


def shell(shape, open_faces, thickness: float) -> TopoDS_Shape:
    """Hollow out a solid, leaving walls `thickness` thick; the chosen faces are removed (open)."""
    if thickness <= 0:
        raise SolidError("The wall thickness must be greater than zero.")
    lst = ShapeList()
    for f in open_faces:
        lst.Append(f)
    mk = BRepOffsetAPI_MakeThickSolid()
    try:
        mk.MakeThickSolidByJoin(shape, lst, -thickness, 1e-4)
        mk.Build()
        ok = mk.IsDone()
    except Exception:                       # noqa: BLE001
        ok = False
    if not ok or mk.Shape().IsNull():
        raise SolidError("The walls can't be that thick for this shape.")
    return mk.Shape()


def half_space(point: Vec3, normal: Vec3, size: float) -> TopoDS_Shape:
    """A big box filling the side of the plane the normal points to."""
    pl = Plane.make(point, normal)
    s = size
    face = face_from_loops(pl, [[(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)]])
    return extrude(face, s, direction=normal)


def slice_solid(shape, point: Vec3, normal: Vec3) -> tuple[TopoDS_Shape | None, TopoDS_Shape | None]:
    """(part on the normal side, part on the other side); either may be None."""
    size = 10 * max(diagonal(shape), 1.0)
    pos = half_space(point, normal, size)
    neg = half_space(point, tuple(-v for v in normal), size)
    a = BRepAlgoAPI_Common(shape, pos).Shape()
    b = BRepAlgoAPI_Common(shape, neg).Shape()
    a = clean(a) if solids_of(a) else None
    b = clean(b) if solids_of(b) else None
    if a is None or b is None:
        raise SolidError("The slicing plane doesn't cut through the solid.")
    return a, b


def presspull(shape, face, distance: float) -> TopoDS_Shape:
    """Push or pull a face: positive adds material outward, negative cuts inward."""
    if abs(distance) < 1e-9:
        raise SolidError("The distance can't be zero.")
    n = np.array(face_normal(face))
    tool = extrude(face, abs(distance), direction=tuple(n if distance > 0 else -n))
    return union(shape, tool) if distance > 0 else subtract(shape, tool)


def transformed(shape, m4: np.ndarray) -> TopoDS_Shape:
    """Apply a 4x4 rigid (or uniformly scaled, possibly mirrored) transform."""
    a = m4[:3, :3]
    s = abs(np.linalg.det(a)) ** (1 / 3)
    trsf = gp_Trsf()
    if np.linalg.det(a) < 0:
        # mirror: reflect in the plane x=0 first (folds the reflection into a gp_Trsf mirror)
        mirror = gp_Trsf()
        mirror.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)))
        r = a @ np.diag([-1.0, 1, 1]) / s
        rest = gp_Trsf()
        rest.SetValues(r[0, 0] * s, r[0, 1] * s, r[0, 2] * s, m4[0, 3], r[1, 0] * s, r[1, 1] * s, r[1, 2] * s,
                       m4[1, 3], r[2, 0] * s, r[2, 1] * s, r[2, 2] * s, m4[2, 3])
        trsf = rest.Multiplied(mirror)
    else:
        trsf.SetValues(a[0, 0], a[0, 1], a[0, 2], m4[0, 3], a[1, 0], a[1, 1], a[1, 2], m4[1, 3],
                       a[2, 0], a[2, 1], a[2, 2], m4[2, 3])
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def translate(shape, d: Vec3) -> TopoDS_Shape:
    m = np.eye(4)
    m[:3, 3] = d
    return transformed(shape, m)


def rotate(shape, axis_point: Vec3, axis_dir: Vec3, angle: float) -> TopoDS_Shape:
    trsf = gp_Trsf()
    trsf.SetRotation(gp_Ax1(P(axis_point), gp_Dir(*axis_dir)), angle)
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def affine2_matrix(m) -> np.ndarray:
    """The 2D drawing transform (Affine2: x' = a x + b y + c, y' = d x + e y + f) as a 4x4 on XY;
    z is scaled by the same factor so solids keep their proportions."""
    a, b, c, d, e, f = m.a, m.b, m.c, m.d, m.e, m.f
    n1, n2, dot = a * a + d * d, b * b + e * e, a * b + d * e
    if abs(n1 - n2) > 1e-9 * max(1.0, n1) or abs(dot) > 1e-9 * max(1.0, n1):
        raise SolidError("Solids can only be moved, rotated, mirrored or scaled evenly.")
    out = np.eye(4)
    out[0, 0], out[0, 1], out[1, 0], out[1, 1] = a, b, d, e
    out[2, 2] = math.sqrt(n1)
    out[0, 3], out[1, 3] = c, f
    return out


# ====================================================================== measuring
def mass_properties(shape) -> dict:
    vp, sp = GProp_GProps(), GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, vp)
    BRepGProp.SurfaceProperties_s(shape, sp)
    c = vp.CentreOfMass()
    return {"volume": vp.Mass(), "area": sp.Mass(), "centroid": (c.X(), c.Y(), c.Z()), "bbox": bbox3(shape)}


def center_of(shape) -> Vec3:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    c = props.CentreOfMass()
    return (c.X(), c.Y(), c.Z())


def bbox3(shape) -> tuple[float, float, float, float, float, float]:
    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b, False)
    if b.IsVoid():
        return (0, 0, 0, 0, 0, 0)
    lo, hi = b.CornerMin(), b.CornerMax()          # (Get() differs between OCP versions)
    return (lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z())


def diagonal(shape) -> float:
    x0, y0, z0, x1, y1, z1 = bbox3(shape)
    return math.dist((x0, y0, z0), (x1, y1, z1))


# ====================================================================== meshes and edges for display
@dataclass
class Mesh:
    vertices: np.ndarray      # (n, 3) float32
    normals: np.ndarray       # (n, 3) float32
    triangles: np.ndarray     # (m, 3) int32
    tri_face: np.ndarray      # (m,) face index of each triangle
    edges: list               # list of (k, 3) float arrays, index = edge index
    edge_kind: list           # "line" | "circle" | "curve"


def _deflection(shape) -> float:
    return max(diagonal(shape) * 1e-3, 1e-4)


_MESH_CACHE: dict = {}


def mesh(shape, deflection: float | None = None) -> Mesh:
    """Triangles (for shading/picking) and edge polylines (for display/snapping). Cached per shape."""
    key = (shape.__hash__(), id(shape))
    hit = _MESH_CACHE.get(key)
    if hit is not None and hit[0] is shape:
        return hit[1]
    defl = deflection or _deflection(shape)
    BRepMesh_IncrementalMesh(shape, defl, False, 0.3, True)
    verts, norms, tris, tri_face = [], [], [], []
    base = 0
    for fi, f in enumerate(faces(shape)):
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(f, loc)
        if tri is None:
            continue
        trsf = loc.Transformation()
        n = tri.NbNodes()
        if not tri.HasNormals():
            BRepLib_ToolTriangulatedShape.ComputeNormals_s(f, tri)
        rev = f.Orientation() == TopAbs_REVERSED
        pts = np.empty((n, 3))
        nrm = np.empty((n, 3))
        for i in range(1, n + 1):
            p = tri.Node(i).Transformed(trsf)
            pts[i - 1] = (p.X(), p.Y(), p.Z())
            d = tri.Normal(i)
            nv = gp_Vec(d.X(), d.Y(), d.Z()).Transformed(trsf)
            nrm[i - 1] = (nv.X(), nv.Y(), nv.Z())
        if rev:
            nrm = -nrm
        t = np.empty((tri.NbTriangles(), 3), dtype=np.int32)
        for i in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(i).Get()
            t[i - 1] = (a - 1, c - 1, b - 1) if rev else (a - 1, b - 1, c - 1)
        verts.append(pts)
        norms.append(nrm)
        tris.append(t + base)
        tri_face.append(np.full(len(t), fi, dtype=np.int32))
        base += n
    edge_lines, kinds = [], []
    for e in edges(shape):
        pts, kind = edge_polyline(e, defl)
        edge_lines.append(pts)
        kinds.append(kind)
    m = Mesh(np.vstack(verts).astype(np.float32) if verts else np.zeros((0, 3), np.float32),
             np.vstack(norms).astype(np.float32) if norms else np.zeros((0, 3), np.float32),
             np.vstack(tris) if tris else np.zeros((0, 3), np.int32),
             np.concatenate(tri_face) if tri_face else np.zeros(0, np.int32),
             edge_lines, kinds)
    if len(_MESH_CACHE) > 500:
        _MESH_CACHE.clear()
    _MESH_CACHE[key] = (shape, m)
    return m


def edge_polyline(e, deflection: float) -> tuple[np.ndarray, str]:
    if BRep_Tool.Degenerated_s(as_edge(e)):
        return np.zeros((0, 3)), "degenerate"
    c = BRepAdaptor_Curve(as_edge(e))
    t = c.GetType()
    kind = "line" if t == GeomAbs_Line else "circle" if t == GeomAbs_Circle else "curve"
    if t == GeomAbs_Line:
        a, b = c.Value(c.FirstParameter()), c.Value(c.LastParameter())
        return np.array([[a.X(), a.Y(), a.Z()], [b.X(), b.Y(), b.Z()]]), kind
    disc = GCPnts_TangentialDeflection(c, 0.15, deflection)
    pts = np.array([[disc.Value(i).X(), disc.Value(i).Y(), disc.Value(i).Z()] for i in range(1, disc.NbPoints() + 1)])
    return pts, kind


def edge_info(e) -> dict:
    """Circle edges: center, radius, axis (for snapping to hole centers)."""
    c = BRepAdaptor_Curve(as_edge(e))
    if c.GetType() == GeomAbs_Circle:
        circ = c.Circle()
        loc, ax = circ.Location(), circ.Axis().Direction()
        return {"kind": "circle", "center": (loc.X(), loc.Y(), loc.Z()), "radius": circ.Radius(),
                "axis": (ax.X(), ax.Y(), ax.Z()), "full": abs(c.LastParameter() - c.FirstParameter() - math.tau) < 1e-6}
    return {"kind": "line" if c.GetType() == GeomAbs_Line else "curve"}


# ====================================================================== projections
def view_projector(direction: Vec3, up: Vec3 = (0, 0, 1)) -> HLRAlgo_Projector:
    """Orthographic projector looking along `direction` (from the eye toward the model)."""
    d = np.array(direction, float)
    d /= np.linalg.norm(d)
    u = np.array(up, float)
    if abs(u @ d) > 0.99:
        u = np.array([0, 1.0, 0]) if abs(d[1]) < 0.9 else np.array([1.0, 0, 0])
    x = np.cross(u, -d)           # right
    x /= np.linalg.norm(x)
    ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*(-d)), gp_Dir(*x))
    return HLRAlgo_Projector(ax)


def view_axes(direction: Vec3, up: Vec3 = (0, 0, 1)) -> tuple[np.ndarray, np.ndarray]:
    """(right, upward) unit vectors of the view, matching view_projector."""
    d = np.array(direction, float)
    d /= np.linalg.norm(d)
    u = np.array(up, float)
    if abs(u @ d) > 0.99:
        u = np.array([0, 1.0, 0]) if abs(d[1]) < 0.9 else np.array([1.0, 0, 0])
    x = np.cross(u, -d)
    x /= np.linalg.norm(x)
    y = np.cross(-d, x)
    return x, y


def hidden_line_view(shape, direction: Vec3, up: Vec3 = (0, 0, 1)) -> dict[str, list[np.ndarray]]:
    """2D polylines of a view: {"visible": [...], "hidden": [...]}, in view coordinates (mm)."""
    algo = HLRBRep_Algo()
    algo.Add(shape)
    algo.Projector(view_projector(direction, up))
    algo.Update()
    algo.Hide()
    to = HLRBRep_HLRToShape(algo)
    out: dict[str, list[np.ndarray]] = {"visible": [], "hidden": []}
    groups = {"visible": [to.VCompound(), to.OutLineVCompound(), to.Rg1LineVCompound()],
              "hidden": [to.HCompound(), to.OutLineHCompound()]}
    defl = _deflection(shape)
    for kind, comps in groups.items():
        for comp in comps:
            if comp is None or comp.IsNull():
                continue
            BRepLib.BuildCurves3d_s(comp)
            for e in edges(comp):
                pts, _ = edge_polyline(e, defl)
                if len(pts) >= 2:
                    out[kind].append(pts[:, :2].copy())
    return out


def plan_primitives(shape):
    """Edges seen from above, as 2D primitives (true arcs for circles lying flat), for the plan view."""
    from .geom2d.primitives import Arc as ArcPrim, Seg
    prims = []
    m = mesh(shape)
    for e, pts, kind in zip(edges(shape), m.edges, m.edge_kind):
        if len(pts) < 2:
            continue
        if kind == "circle":
            info = edge_info(e)
            ax = info["axis"]
            if abs(abs(ax[2]) - 1) < 1e-9:
                c = info["center"]
                if info["full"]:
                    prims.append(ArcPrim((c[0], c[1]), info["radius"], 0.0, math.tau))
                    continue
                a0 = math.atan2(pts[0][1] - c[1], pts[0][0] - c[0])
                a1 = math.atan2(pts[-1][1] - c[1], pts[-1][0] - c[0])
                mid = pts[len(pts) // 2]
                am = math.atan2(mid[1] - c[1], mid[0] - c[0])
                sweep = (a1 - a0) % math.tau
                if not ((am - a0) % math.tau <= sweep):
                    sweep -= math.tau
                prims.append(ArcPrim((c[0], c[1]), info["radius"], a0, sweep))
                continue
        xy = pts[:, :2]
        for i in range(len(xy) - 1):
            a, b = tuple(xy[i]), tuple(xy[i + 1])
            if math.dist(a, b) > 1e-9:
                prims.append(Seg(a, b))
    return prims


_PLAN_CACHE: dict = {}


def cached_plan_primitives(shape) -> list:
    key = id(shape)
    hit = _PLAN_CACHE.get(key)
    if hit is not None and hit[0] is shape:
        return hit[1]
    prims = plan_primitives(shape) if shape is not None else []
    if len(_PLAN_CACHE) > 500:
        _PLAN_CACHE.clear()
    _PLAN_CACHE[key] = (shape, prims)
    return prims


def section_edges(shape, plane: Plane) -> list[np.ndarray]:
    """Where a plane cuts a solid, as polylines in the plane's 2D coordinates."""
    sec = BRepAlgoAPI_Section(shape, gp_Pln(plane.ax3()), False)
    sec.ComputePCurveOn1(True)
    sec.Approximation(True)
    sec.Build()
    out = []
    defl = _deflection(shape)
    for e in edges(sec.Shape()):
        pts, _ = edge_polyline(e, defl)
        if len(pts) >= 2:
            out.append(np.array([plane.to_local(p)[:2] for p in pts]))
    return out


# ====================================================================== picking
def ray_hit(m: Mesh, origin: np.ndarray, direction: np.ndarray) -> tuple[float, int] | None:
    """Nearest triangle hit by a ray: (distance, face index) — Moller-Trumbore, vectorized."""
    if not len(m.triangles):
        return None
    v0 = m.vertices[m.triangles[:, 0]].astype(np.float64)
    v1 = m.vertices[m.triangles[:, 1]].astype(np.float64)
    v2 = m.vertices[m.triangles[:, 2]].astype(np.float64)
    e1, e2 = v1 - v0, v2 - v0
    pv = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, pv)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    tv = origin - v0
    u = np.einsum("ij,ij->i", tv, pv) * inv
    qv = np.cross(tv, e1)
    v = (qv @ direction) * inv
    t = np.einsum("ij,ij->i", e2, qv) * inv
    hit = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 1e-9)
    if not hit.any():
        return None
    i = int(np.argmin(np.where(hit, t, np.inf)))
    return float(t[i]), int(m.tri_face[i])


def nearest_edge(m: Mesh, point: Vec3, max_dist: float | None = None) -> int | None:
    """Index of the edge closest to a 3D point."""
    p = np.array(point, float)
    best, bi = math.inf, None
    for i, pts in enumerate(m.edges):
        if len(pts) < 2:
            continue
        a, b = pts[:-1], pts[1:]
        d = b - a
        L2 = np.einsum("ij,ij->i", d, d)
        t = np.clip(np.einsum("ij,ij->i", p - a, d) / np.where(L2 > 0, L2, 1), 0, 1)
        q = a + d * t[:, None]
        dist = float(np.min(np.linalg.norm(q - p, axis=1)))
        if dist < best:
            best, bi = dist, i
    if max_dist is not None and best > max_dist:
        return None
    return bi


@lru_cache(maxsize=1)
def ocp_version() -> str:
    try:
        import OCP
        return str(getattr(OCP, "__version__", "?"))
    except Exception:                       # noqa: BLE001
        return "?"


__all__ = [n for n in dir() if not n.startswith("_") and n not in ("annotations",)]
_ = (TopoDS_Compound, gp_Dir)
