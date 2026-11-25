import math

import pytest

from cad.commands import CommandContext, CommandRunner
from cad.core.constraints import (
    Constraint, ConstraintError, ConstraintManager, ExpressionError, evaluate, solve_for, would_overconstrain,
)
from cad.core.model import Circle, Document, Line, Polyline
from cad.core.spatial import SpatialIndex
from cad.io import native


@pytest.fixture
def env():
    doc = Document()
    mgr = ConstraintManager(doc)
    ctx = CommandContext(doc=doc, index=SpatialIndex(doc), constraints=mgr)
    return doc, CommandRunner(ctx)


def seed(doc, *ents):
    with doc.transaction("seed"):
        return [doc.add(e) for e in ents]


def add(doc, c):
    with doc.transaction("c"):
        doc.set_item("constraint", c.id, c)


def test_expressions():
    assert evaluate("2*(3+4)", {}) == 14
    assert evaluate("d1/2 + sqrt(16)", {"d1": 10}) == 9
    assert evaluate("sin(30)", {}) == pytest.approx(0.5)
    for bad in ("__import__('os')", "d9", "1/0", "a b"):
        with pytest.raises(ExpressionError):
            evaluate(bad, {})


def test_horizontal_parallel_perpendicular(env):
    doc, _ = env
    a, b = seed(doc, Line(p1=(0, 0), p2=(10, 1)), Line(p1=(0, 5), p2=(3, 9)))
    add(doc, Constraint(1, "horizontal", ((a.handle, "line"),)))
    l1 = doc.get(a.handle)
    assert l1.p1[1] == pytest.approx(l1.p2[1], abs=1e-9)
    add(doc, Constraint(2, "perpendicular", ((a.handle, "line"), (b.handle, "line"))))
    l2 = doc.get(b.handle)
    assert l2.p1[0] == pytest.approx(l2.p2[0], abs=1e-7)


def test_coincident_and_dimension_drive_geometry(env):
    doc, _ = env
    a, b = seed(doc, Line(p1=(0, 0), p2=(10, 0)), Line(p1=(10.5, 0.3), p2=(10, 8)))
    add(doc, Constraint(1, "coincident", ((a.handle, "p2"), (b.handle, "p1"))))
    assert doc.get(b.handle).p1 == pytest.approx(doc.get(a.handle).p2, abs=1e-8)
    add(doc, Constraint(2, "distance", ((a.handle, "p1"), (a.handle, "p2")), name="d1", expression="25"))
    la, lb = doc.get(a.handle), doc.get(b.handle)
    assert math.dist(la.p1, la.p2) == pytest.approx(25, abs=1e-7)
    assert lb.p1 == pytest.approx(la.p2, abs=1e-7)          # still connected
    # editing the parameter re-solves
    add(doc, Constraint(2, "distance", ((a.handle, "p1"), (a.handle, "p2")), name="d1", expression="40"))
    la = doc.get(a.handle)
    assert math.dist(la.p1, la.p2) == pytest.approx(40, abs=1e-7)
    doc.undo()
    assert math.dist(doc.get(a.handle).p1, doc.get(a.handle).p2) == pytest.approx(25, abs=1e-7)


def test_moving_constrained_geometry_keeps_constraints(env):
    doc, _ = env
    a, b = seed(doc, Line(p1=(0, 0), p2=(10, 0)), Line(p1=(10, 0), p2=(10, 10)))
    add(doc, Constraint(1, "coincident", ((a.handle, "p2"), (b.handle, "p1"))))
    add(doc, Constraint(2, "perpendicular", ((a.handle, "line"), (b.handle, "line"))))
    with doc.transaction("move"):
        doc.replace(doc.get(a.handle).with_props(p2=(20, 0)) if False else
                    Line(handle=a.handle, p1=(0, 0), p2=(20, 0)))
    la, lb = doc.get(a.handle), doc.get(b.handle)
    assert la.p2 == pytest.approx((20, 0), abs=1e-6)        # the edited line stays where it was put
    assert lb.p1 == pytest.approx((20, 0), abs=1e-6)        # the other follows


def test_conflict_is_refused_and_rolled_back(env):
    doc, _ = env
    (a,) = seed(doc, Line(p1=(0, 0), p2=(10, 0)))
    add(doc, Constraint(1, "fix", ((a.handle, "p1"),), values=(0.0, 0.0)))
    add(doc, Constraint(2, "fix", ((a.handle, "p2"),), values=(10.0, 0.0)))
    before = dict(doc.entities)
    with pytest.raises(ConstraintError):
        add(doc, Constraint(3, "distance", ((a.handle, "p1"), (a.handle, "p2")), name="d1", expression="5"))
    assert doc.entities == before and 3 not in doc.constraints


def test_overconstrain_detection(env):
    doc, _ = env
    a, b = seed(doc, Line(p1=(0, 0), p2=(10, 0)), Line(p1=(0, 5), p2=(10, 5)))
    add(doc, Constraint(1, "horizontal", ((a.handle, "line"),)))
    add(doc, Constraint(2, "parallel", ((a.handle, "line"), (b.handle, "line"))))
    assert would_overconstrain(doc, Constraint(3, "horizontal", ((b.handle, "line"),)))
    assert not would_overconstrain(doc, Constraint(3, "equal", ((a.handle, "line"), (b.handle, "line"))))


def test_dof_and_polyline_and_circles(env):
    doc, _ = env
    sq, c1, c2 = seed(doc, Polyline(vertices=((0, 0, 0), (10, 0.2, 0), (10.1, 10, 0), (0, 9.8, 0)), closed=True),
                      Circle(center=(30, 0), radius=5), Circle(center=(31, 0.5), radius=2))
    for i, kind in enumerate(("horizontal", "vertical", "horizontal", "vertical")):
        add(doc, Constraint(i + 1, kind, ((sq.handle, f"seg{i}"),)))
    vs = doc.get(sq.handle).vertices
    assert vs[0][1] == pytest.approx(vs[1][1], abs=1e-7) and vs[1][0] == pytest.approx(vs[2][0], abs=1e-7)
    res = solve_for(doc, {sq.handle})
    assert res.dof == 4                       # rectangle: position (2) + width + height
    add(doc, Constraint(10, "concentric", ((c1.handle, "circle"), (c2.handle, "circle"))))
    assert doc.get(c2.handle).center == pytest.approx(doc.get(c1.handle).center, abs=1e-7)
    add(doc, Constraint(11, "radius", ((c2.handle, "circle"),), name="rad1", expression="3"))
    add(doc, Constraint(12, "diameter", ((c1.handle, "circle"),), name="dia1", expression="rad1*4"))
    assert doc.get(c1.handle).radius == pytest.approx(6, abs=1e-7)


def test_constraints_saved_and_deleted_with_objects(env, tmp_path):
    doc, _ = env
    a, b = seed(doc, Line(p1=(0, 0), p2=(10, 0)), Line(p1=(0, 5), p2=(10, 6)))
    add(doc, Constraint(1, "parallel", ((a.handle, "line"), (b.handle, "line"))))
    p = str(tmp_path / "c.cadz")
    native.save(doc, p)
    d2, _ = native.load(p)
    assert d2.constraints[1].kind == "parallel"
    with doc.transaction("del"):
        doc.delete(b.handle)
    assert not doc.constraints


def test_constraint_commands(env):
    doc, r = env
    a, b, c = seed(doc, Line(p1=(0, 0), p2=(10, 1)), Line(p1=(10, 1), p2=(12, 9)), Circle(center=(30, 0), radius=4))

    def go(*items):
        for it in items:
            if isinstance(it, tuple):
                r.submit_point(it)
            else:
                assert r.submit_text(it) is not False, r.ctx.messages[-3:]
    go("GCHORIZONTAL", (5, 0.5))
    assert doc.get(a.handle).p1[1] == pytest.approx(doc.get(a.handle).p2[1], abs=1e-7)
    go("GCPERPENDICULAR", (5, doc.get(a.handle).p1[1]), (11, 5))
    go("DCALIGNED", (0.1, doc.get(a.handle).p1[1]), (9.9, doc.get(a.handle).p2[1]), "2in")
    la = doc.get(a.handle)
    assert math.dist(la.p1, la.p2) == pytest.approx(50.8, abs=1e-6)
    go("DCRADIUS", (34, 0), "d1/10")
    assert doc.get(c.handle).radius == pytest.approx(5.08, abs=1e-6)
    go("GCHORIZONTAL", (doc.get(a.handle).p1[0] + 1, doc.get(a.handle).p1[1]))
    assert "over-constrain" in r.ctx.messages[-1]
    r.ctx.selection = {c.handle}
    go("DELCONSTRAINT")
    assert all(c.handle not in k.handles for k in doc.constraints.values())
