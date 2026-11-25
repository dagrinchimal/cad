"""Command framework.

A command is a generator. It *yields* requests (GetPoint, GetDistance, ...)
and receives the user's answer. This mirrors AutoCAD's prompt-driven flow and
keeps commands free of UI code, so they can be driven by the mouse, the
command line, scripts or tests alike.

    @command("LINE", label="Line", aliases=("L",), description="...")
    def line(ctx):
        p1 = yield GetPoint("Specify first point")
        ...
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Generator, Iterable, Protocol

from rapidfuzz import fuzz, process

from ..core.geom2d.vec import Vec, dist, polar
from ..core.model import Document, Entity
from ..core.spatial import SpatialIndex
from ..core.units import UnitParseError, UnitSettings, format_length, parse_angle, parse_length


class CommandCancelled(Exception):
    """Thrown into a command generator when the user presses Esc."""


@dataclass(frozen=True, slots=True)
class Keyword:
    name: str            # e.g. "Close"
    key: str = ""        # shortcut letters, e.g. "C" (defaults to the capital letters / first letter)

    @property
    def shortcut(self) -> str:
        if self.key:
            return self.key.upper()
        caps = "".join(c for c in self.name if c.isupper() or c.isdigit())
        return caps or self.name[0].upper()

    def matches(self, text: str) -> bool:
        t = text.strip().upper()
        return t == self.name.upper() or t == self.shortcut


# ------------------------------------------------------------------ requests
@dataclass(slots=True)
class Request:
    prompt: str
    keywords: tuple[Keyword, ...] = ()
    allow_none: bool = False                 # Enter with no input is a valid answer (None)
    default: Any = None                      # used when Enter is pressed
    default_text: str = ""

    def full_prompt(self) -> str:
        text = self.prompt
        if self.keywords:
            text += " or [" + "/".join(k.name for k in self.keywords) + "]"
        if self.default_text:
            text += f" <{self.default_text}>"
        return text + ":"

    def match_keyword(self, text: str) -> Keyword | None:
        for k in self.keywords:
            if k.matches(text):
                return k
        return None


PreviewFn = Callable[[Vec], list[Entity]]


@dataclass(slots=True)
class GetPoint(Request):
    base: Vec | None = None
    rubber: str | None = "line"              # "line", "rect" or None
    preview: PreviewFn | None = None
    mode: str = "point"                      # "point" or "pan"


@dataclass(slots=True)
class GetDistance(Request):
    base: Vec | None = None
    preview: PreviewFn | None = None
    positive: bool = True


@dataclass(slots=True)
class GetKeyword(Request):
    pass


@dataclass(slots=True)
class GetString(Request):
    pass


@dataclass(slots=True)
class GetSelection(Request):
    use_pickfirst: bool = True


def kw(*names: str) -> tuple[Keyword, ...]:
    return tuple(Keyword(n) for n in names)


# ------------------------------------------------------------------ context
class ViewApi(Protocol):
    def zoom_extents(self) -> None: ...
    def zoom_window(self, p1: Vec, p2: Vec) -> None: ...
    def zoom_previous(self) -> bool: ...
    def zoom_factor(self, factor: float) -> None: ...
    def regen(self) -> None: ...


class UiApi(Protocol):
    def run_ui_action(self, name: str) -> None: ...


class _NullView:
    def zoom_extents(self) -> None: ...
    def zoom_window(self, p1: Vec, p2: Vec) -> None: ...
    def zoom_previous(self) -> bool: return False
    def zoom_factor(self, factor: float) -> None: ...
    def regen(self) -> None: ...


class _NullUi:
    def run_ui_action(self, name: str) -> None: ...


@dataclass
class CommandContext:
    doc: Document
    index: SpatialIndex
    selection: set[int] = field(default_factory=set)     # pick-first selection
    view: ViewApi = field(default_factory=_NullView)
    ui: UiApi = field(default_factory=_NullUi)
    last_point: Vec | None = None
    memory: dict = field(default_factory=dict)            # per-command remembered values
    messages: list[str] = field(default_factory=list)
    on_message: Callable[[str], None] | None = None

    @property
    def units(self) -> UnitSettings:
        return self.doc.header.units

    def fmt(self, mm: float) -> str:
        return format_length(mm, self.units)

    def echo(self, text: str) -> None:
        self.messages.append(text)
        if self.on_message:
            self.on_message(text)


CommandFunc = Callable[[CommandContext], Generator[Request, Any, None]]


@dataclass(frozen=True, slots=True)
class CommandDef:
    name: str                       # canonical, upper case: "LINE"
    func: CommandFunc
    label: str                      # "Line"
    description: str                # one line
    aliases: tuple[str, ...] = ()
    shortcut: str = ""              # keyboard shortcut shown in tooltips, e.g. "Ctrl+Z"
    group: str = ""                 # ribbon group
    icon: str = ""
    help_id: str = ""
    transaction: bool = True        # wrap in an undo step
    repeatable: bool = True
    keywords: tuple[str, ...] = ()  # extra search words

    @property
    def tooltip_shortcut(self) -> str:
        parts = []
        if self.aliases:
            parts.append(self.aliases[0])
        if self.shortcut:
            parts.append(self.shortcut)
        return " / ".join(parts)


class CommandRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, CommandDef] = {}
        self._alias: dict[str, str] = {}

    def register(self, cmd: CommandDef) -> CommandDef:
        name = cmd.name.upper()
        if name in self._by_name:
            raise ValueError(f"Command {name} already registered")
        self._by_name[name] = cmd
        for a in cmd.aliases:
            self._alias[a.upper()] = name
        return cmd

    def get(self, text: str) -> CommandDef | None:
        t = text.strip().upper().lstrip("_.'")
        name = self._alias.get(t, t)
        return self._by_name.get(name)

    def all(self) -> list[CommandDef]:
        return list(self._by_name.values())

    def search(self, text: str, limit: int = 8) -> list[CommandDef]:
        """Suggestions for the command line: prefix matches first, then fuzzy."""
        t = text.strip().upper()
        if not t:
            return []
        out: list[CommandDef] = []
        seen: set[str] = set()

        def push(c: CommandDef) -> None:
            if c.name not in seen:
                seen.add(c.name)
                out.append(c)

        exact = self.get(t)
        if exact:
            push(exact)
        for c in sorted(self._by_name.values(), key=lambda c: c.name):
            if c.name.startswith(t) or c.label.upper().startswith(t) or any(a.upper() == t for a in c.aliases):
                push(c)
        choices = {}
        for c in self._by_name.values():
            choices[c.name] = f"{c.name} {c.label} {' '.join(c.aliases)} {c.description} {' '.join(c.keywords)}".upper()
        for _, score, name in process.extract(t, choices, scorer=fuzz.WRatio, limit=limit * 2):
            if score >= 60:
                push(self._by_name[name])
        return out[:limit]


REGISTRY = CommandRegistry()


def command(name: str, *, label: str, description: str, aliases: Iterable[str] = (), shortcut: str = "",
            group: str = "", icon: str = "", help_id: str = "", transaction: bool = True,
            repeatable: bool = True, keywords: Iterable[str] = (),
            registry: CommandRegistry | None = None) -> Callable[[CommandFunc], CommandFunc]:
    def deco(fn: CommandFunc) -> CommandFunc:
        (registry or REGISTRY).register(CommandDef(
            name=name.upper(), func=fn, label=label, description=description, aliases=tuple(aliases),
            shortcut=shortcut, group=group, icon=icon or name.lower(), help_id=help_id or name.lower(),
            transaction=transaction, repeatable=repeatable, keywords=tuple(keywords)))
        return fn
    return deco


# ------------------------------------------------------------------ coordinate input
class InputError(ValueError):
    pass


_RE_NUMBERISH = re.compile(r"[0-9.]")


def parse_point_text(text: str, units: UnitSettings, last: Vec | None,
                     direction: float | None) -> Vec:
    """Turn typed input into a point.

    10,20      absolute            #10,20    absolute (explicit)
    @10,20     relative to last    @50<30    polar relative to last
    50<30      polar from origin   @         the last point
    50         direct distance along the current rubber-band direction
    """
    t = text.strip()
    if not t:
        raise InputError("Empty input")
    relative = False
    if t.startswith("@"):
        relative = True
        t = t[1:].strip()
        if last is None:
            raise InputError("There's no last point to measure from yet")
        if not t:
            return last
    elif t.startswith("#"):
        t = t[1:].strip()
    try:
        if "<" in t:
            d_text, a_text = t.split("<", 1)
            d = parse_length(d_text, units)
            a = math.radians(parse_angle(a_text))
            origin = last if relative else (0.0, 0.0)
            return polar(origin, a, d)
        if "," in t:
            parts = [p for p in t.split(",")]
            if len(parts) not in (2, 3):
                raise InputError("Enter a point as x,y")
            x, y = parse_length(parts[0], units), parse_length(parts[1], units)
            if relative:
                return (last[0] + x, last[1] + y)
            return (x, y)
        d = parse_length(t, units)
    except UnitParseError as exc:
        raise InputError(str(exc)) from exc
    if relative:
        raise InputError("Use @x,y or @distance<angle")
    if last is None or direction is None:
        raise InputError("Enter a point as x,y (a single distance needs a previous point)")
    return polar(last, direction, d)


# ------------------------------------------------------------------ runner
class CommandRunner:
    """Drives one command at a time. UI-independent: the UI calls submit_*()."""

    def __init__(self, ctx: CommandContext, registry: CommandRegistry = REGISTRY) -> None:
        self.ctx = ctx
        self.registry = registry
        self.active: CommandDef | None = None
        self.request: Request | None = None
        self._gen: Generator | None = None
        self._own_tx = False
        self.last_command: CommandDef | None = None
        self.direction_provider: Callable[[], float | None] = lambda: None
        self.listeners: list[Callable[[], None]] = []

    # ----------------------------------------------------------- state
    @property
    def is_active(self) -> bool:
        return self.active is not None

    @property
    def prompt(self) -> str:
        if self.request is not None:
            return self.request.full_prompt()
        return "Type a command"

    def _changed(self) -> None:
        for fn in list(self.listeners):
            fn()

    # ----------------------------------------------------------- start/stop
    def run(self, cmd: CommandDef | str) -> bool:
        if isinstance(cmd, str):
            found = self.registry.get(cmd)
            if found is None:
                self.ctx.echo(f'Unknown command "{cmd.strip().upper()}". Type part of a name to see suggestions.')
                return False
            cmd = found
        if self.active is not None:
            self.cancel()
        self.active = cmd
        if cmd.repeatable:
            self.last_command = cmd
        self.ctx.echo(f"Command: {cmd.name}")
        self._own_tx = False
        if cmd.transaction and not self.ctx.doc.in_transaction:
            self.ctx.doc.begin(cmd.label)
            self._own_tx = True
        self._gen = cmd.func(self.ctx)
        self._step(lambda: next(self._gen))
        return True

    def repeat_last(self) -> bool:
        if self.last_command is None:
            return False
        return self.run(self.last_command)

    def cancel(self) -> None:
        if self._gen is None:
            return
        gen = self._gen
        try:
            req = gen.throw(CommandCancelled())
        except (CommandCancelled, StopIteration):
            req = None
        except Exception as exc:          # noqa: BLE001 - report, never crash the UI
            self._fail(exc)
            return
        if req is not None:
            gen.close()
        self.ctx.echo("*Cancel*")
        self._finish()

    def _finish(self) -> None:
        self._gen = None
        self.request = None
        self.active = None
        if self._own_tx and self.ctx.doc.in_transaction:
            self.ctx.doc.commit()
        self._own_tx = False
        self.ctx.doc.flush()
        self._changed()

    def _fail(self, exc: Exception) -> None:
        self.ctx.echo(f"Error: {exc}")
        self._gen = None
        self.request = None
        self.active = None
        if self._own_tx and self.ctx.doc.in_transaction:
            self.ctx.doc.rollback()
        self._own_tx = False
        self._changed()

    def _step(self, advance: Callable[[], Request]) -> None:
        try:
            req = advance()
        except StopIteration:
            self._finish()
            return
        except CommandCancelled:
            self._finish()
            return
        except Exception as exc:          # noqa: BLE001
            self._fail(exc)
            return
        self.request = req
        self.ctx.doc.flush()
        if isinstance(req, GetSelection) and req.use_pickfirst and self.ctx.selection:
            sel = set(self.ctx.selection)
            self.ctx.selection.clear()
            self._send(sel)
            return
        self._changed()

    def _send(self, value: Any) -> None:
        if self._gen is None:
            return
        if isinstance(value, tuple) and len(value) == 2 and isinstance(self.request, (GetPoint,)):
            self.ctx.last_point = value
        gen = self._gen
        self._step(lambda: gen.send(value))

    # ----------------------------------------------------------- input from the UI
    def submit_point(self, pt: Vec) -> None:
        """A point picked with the mouse (already snapped)."""
        req = self.request
        if isinstance(req, GetPoint):
            self._send(pt)
        elif isinstance(req, GetDistance):
            if req.base is None:
                self.ctx.echo("Type a distance")
                return
            self._send(dist(req.base, pt))

    def submit_selection(self, handles: set[int]) -> None:
        if isinstance(self.request, GetSelection):
            self._send(set(handles))

    def submit_keyword(self, name: str) -> None:
        if self.request and any(k.name == name for k in self.request.keywords):
            self._send(name)

    def submit_enter(self) -> None:
        """Enter / Space / right-click 'Enter' with no typed text."""
        req = self.request
        if req is None:
            return
        if req.default is not None:
            self._send(req.default)
        elif req.allow_none or isinstance(req, GetSelection):
            self._send(None)
        else:
            self.ctx.echo("A value is required. Press Esc to cancel.")

    def submit_text(self, text: str) -> bool:
        """Text typed in the command line. Returns False if it wasn't accepted."""
        t = text.strip()
        if self.request is None:
            if not t:
                return self.repeat_last()
            return self.run(t)
        if not t:
            self.submit_enter()
            return True
        req = self.request
        k = req.match_keyword(t)
        if k is not None:
            self._send(k.name)
            return True
        try:
            if isinstance(req, GetPoint):
                pt = parse_point_text(t, self.ctx.units, req.base if req.base is not None else self.ctx.last_point,
                                      self.direction_provider())
                self.ctx.last_point = pt
                self._send(pt)
            elif isinstance(req, GetDistance):
                if "," in t or "<" in t or t.startswith("@"):
                    pt = parse_point_text(t, self.ctx.units, req.base, None)
                    if req.base is None:
                        raise InputError("Type a distance")
                    value = dist(req.base, pt)
                else:
                    value = parse_length(t, self.ctx.units)
                if req.positive and value <= 0:
                    raise InputError("The value must be greater than zero")
                self._send(value)
            elif isinstance(req, GetString):
                self._send(text)
            elif isinstance(req, GetSelection):
                if t.upper() == "ALL":
                    self._send({h for h, e in self.ctx.doc.entities.items() if self.ctx.doc.is_visible(e)})
                else:
                    raise InputError("Pick objects, type ALL, or press Enter when done")
            else:
                raise InputError("Choose one of the options: " + ", ".join(k.name for k in req.keywords))
        except (InputError, UnitParseError) as exc:
            self.ctx.echo(f"Invalid input: {exc}")
            return False
        return True

    # ----------------------------------------------------------- preview
    def preview(self, cursor: Vec) -> list[Entity]:
        req = self.request
        fn = getattr(req, "preview", None)
        if fn is None:
            return []
        try:
            return list(fn(cursor))
        except Exception:                 # noqa: BLE001 - a preview must never break input
            return []


def fmt_dist(ctx: CommandContext, v: float) -> str:
    return format_length(v, ctx.units)
