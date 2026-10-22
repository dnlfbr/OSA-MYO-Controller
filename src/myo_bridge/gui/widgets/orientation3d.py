"""Arm view: the armband drawn on a forearm with a hand, in software 3D (QPainter, no OpenGL).

Frames
- Myo sensor frame: x along the forearm (toward the wrist or toward the elbow: the sync event
  reports which, as x_direction), z out of the logo pod, y = z × x.
- Quaternion world frame: Z up (gravity), heading arbitrary until SET ORIGIN.
- Model (arm) frame: x toward the hand, z out of the logo pod. When the band's +x points to the
  elbow the model is turned 180° about z (and the heading by 180°, so after SET ORIGIN the hand
  still points forward); the FLIP button does the same by hand when the sync didn't say.

The default camera looks over the wearer's shoulder: point at the screen, press SET ORIGIN and
the model points into the screen, rises when the arm rises and turns with it."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from myo_bridge.gui import theme
from myo_bridge.gui.theme import Panel, label
from myo_bridge.processing import quaternion as Q

VIEWS = ("behind", "side", "top", "mirror")
VIEW_HELP = {
    "behind": "over the shoulder: the arm points into the screen",
    "side": "from the right: raising the arm raises the model",
    "top": "from above: the arm points up the screen",
    "mirror": "facing you, like a mirror",
}

_FLIP: Q.Quat = (0.0, 0.0, 0.0, 1.0)  # 180° about z
_GROUND_Z = -1.3


# ---------------------------------------------------------------- geometry (model frame)
def _box(x0, x1, y0, y1, z0, z1) -> np.ndarray:
    return np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], dtype=float)


_BOX_FACES = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))


@dataclass
class Part:
    verts: np.ndarray  # (n, 3) model frame
    faces: tuple  # index tuples, any winding (outward is taken from the part centre)
    color: str
    edge: str | None = None
    shadow: bool = True


def _forearm() -> Part:
    """Elliptic frustum, elbow (x<0) wider than the wrist; split along x for depth sorting."""
    n_around, xs = 18, np.linspace(-1.05, 0.80, 7)
    verts = []
    for x in xs:
        k = (x - xs[0]) / (xs[-1] - xs[0])
        ry, rz = 0.36 + (0.27 - 0.36) * k, 0.30 + (0.17 - 0.30) * k
        for i in range(n_around):
            a = 2 * math.pi * i / n_around
            verts.append((x, ry * math.cos(a), rz * math.sin(a)))
    faces = []
    for r in range(len(xs) - 1):
        for i in range(n_around):
            j = (i + 1) % n_around
            faces.append((r * n_around + i, r * n_around + j, (r + 1) * n_around + j, (r + 1) * n_around + i))
    faces.append(tuple(range(n_around)))  # elbow cap
    faces.append(tuple(range((len(xs) - 1) * n_around, len(xs) * n_around)))  # wrist cap
    return Part(np.array(verts), tuple(faces), "#6F6A63")


def _band() -> list[Part]:
    """Eight pods around the forearm near the elbow; pod 0 (copper) is the logo pod, on +z."""
    xc, half_len = -0.55, 0.15
    k = (xc + 1.05) / 1.85
    ry, rz = 0.36 + (0.27 - 0.36) * k, 0.30 + (0.17 - 0.30) * k
    parts = []
    for p in range(8):
        a = math.pi / 2 + p * math.pi / 4
        r = ry * rz / math.hypot(rz * math.cos(a), ry * math.sin(a))
        n = np.array([0.0, math.cos(a), math.sin(a)])
        t = np.array([0.0, -math.sin(a), math.cos(a)])
        hw = r * math.sin(math.pi / 8) * 0.80
        verts = []
        for dx in (-half_len, half_len):
            for dt in (-hw, hw):
                for dr in (r + 0.01, r + 0.085):
                    verts.append(np.array([xc + dx, 0, 0]) + dt * t + dr * n)
        logo = p == 0
        parts.append(Part(np.array(verts), _BOX_FACES, theme.COPPER if logo else "#34312E",
                          edge="#E8B08A" if logo else "#55504A", shadow=False))
    return parts


def _hand(arm: str) -> list[Part]:
    """Palm toward -z (the logo pod is assumed on the back of the forearm), fingers toward +x.
    The thumb goes on +y for a right arm, -y for a left arm; none when the arm is unknown."""
    skin, edge = "#7D776F", "#9A938A"
    parts = [Part(_box(0.82, 1.38, -0.25, 0.25, -0.085, 0.075), _BOX_FACES, skin, edge)]
    for i in range(4):
        y0 = -0.24 + i * 0.125
        length = (0.30, 0.36, 0.34, 0.26)[i if arm != "left" else 3 - i]
        parts.append(Part(_box(1.40, 1.40 + length, y0, y0 + 0.105, -0.06, 0.05), _BOX_FACES, skin, edge))
    if arm in ("right", "left"):
        s = 1.0 if arm == "right" else -1.0
        v = _box(0.0, 0.34, -0.055, 0.055, -0.06, 0.04)
        ang = math.radians(35) * s  # splayed toward the thumb side
        rot = np.array([[math.cos(ang), -math.sin(ang), 0], [math.sin(ang), math.cos(ang), 0], [0, 0, 1]])
        v = v @ rot.T + np.array([0.95, s * 0.25, -0.03])
        parts.append(Part(v, _BOX_FACES, skin, edge))
    return parts


# ---------------------------------------------------------------- camera
@dataclass(frozen=True)
class Camera:
    eye: tuple[float, float, float]
    target: tuple[float, float, float]
    up: tuple[float, float, float] = (0.0, 0.0, 1.0)
    mirror: bool = False
    focal: float = 3.0

    def basis(self) -> tuple[np.ndarray, np.ndarray]:
        eye = np.array(self.eye, dtype=float)
        f = np.array(self.target, dtype=float) - eye
        f /= np.linalg.norm(f)
        r = np.cross(f, np.array(self.up, dtype=float))
        r /= np.linalg.norm(r)
        u = np.cross(r, f)
        return eye, np.stack((r, u, f))


CAMERAS = {
    "behind": Camera(eye=(-4.6, -2.3, 2.5), target=(0.5, 0.0, -0.3), focal=4.4),
    "side": Camera(eye=(0.35, -6.2, 1.1), target=(0.35, 0.0, -0.35), focal=4.6),
    "top": Camera(eye=(0.35, 0.0, 6.6), target=(0.35, 0.0, 0.0), up=(1.0, 0.0, 0.0), focal=4.4),
    "mirror": Camera(eye=(5.6, -1.5, 2.1), target=(0.3, 0.0, -0.3), mirror=True, focal=4.4),
}


def rot_matrix(q: Q.Quat) -> np.ndarray:
    w, x, y, z = Q.normalize(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def model_quat(q: Q.Quat, toward_elbow: bool) -> Q.Quat:
    """Quaternion that turns the model (x = hand, z = logo pod) into the world, given the band's q."""
    if not toward_elbow:
        return q
    return Q.multiply(_FLIP, Q.multiply(q, _FLIP))


def to_camera(points: np.ndarray, view: str = "behind") -> np.ndarray:
    eye, basis = CAMERAS[view].basis()
    return (points - eye) @ basis.T  # columns: right, up, depth


def project(points: np.ndarray, q: Q.Quat, view: str = "behind", toward_elbow: bool = False) -> np.ndarray:
    """Model-frame points → screen coordinates (x right, y up, focal-plane units)."""
    world = points @ rot_matrix(model_quat(q, toward_elbow)).T
    return _perspective(to_camera(world, view), view)


def _perspective(cam: np.ndarray, view: str) -> np.ndarray:
    c = CAMERAS[view]
    depth = np.maximum(cam[:, 2], 0.2)
    xy = c.focal * cam[:, :2] / depth[:, None]
    if c.mirror:
        xy[:, 0] = -xy[:, 0]
    return xy


def _hull(pts: np.ndarray) -> np.ndarray:
    """Convex hull (monotone chain) of 2-D points, counter-clockwise."""
    p = sorted(set(map(tuple, np.round(pts, 5))))
    if len(p) < 3:
        return np.array(p)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for pt in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], pt) <= 0:
            lower.pop()
        lower.append(pt)
    for pt in reversed(p):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], pt) <= 0:
            upper.pop()
        upper.append(pt)
    return np.array(lower[:-1] + upper[:-1])


_LIGHT = np.array([-0.35, -0.45, 0.82]) / np.linalg.norm([-0.35, -0.45, 0.82])


class ArmCanvas(QWidget):
    """Draws the ground grid, the arm's shadow and the shaded arm, back to front."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view = "behind"
        self.q: Q.Quat = Q.IDENTITY
        self.toward_elbow = False
        self.arm = "unknown"
        self._compile()

    def set_arm(self, arm: str) -> None:
        if arm != self.arm:
            self.arm = arm
            self._compile()
            self.update()

    def _compile(self) -> None:
        """Flatten the parts into one vertex array plus per-face index lists, outward normals,
        centres and colours (all in the model frame), so a frame is a few matrix products."""
        parts = [_forearm(), *_band(), *_hand(self.arm)]
        verts, faces, normals, centres, base, edges, shadow = [], [], [], [], [], [], []
        off = 0
        for part in parts:
            centre = part.verts.mean(axis=0)
            rgb = QColor(part.color)
            for f in part.faces:
                pw = part.verts[list(f)]
                n = np.zeros(3)  # Newell's method: robust for any planar-ish polygon
                for a, b in zip(pw, np.roll(pw, -1, axis=0)):
                    n += ((a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1]))
                fc = pw.mean(axis=0)
                if np.dot(n, fc - centre) < 0:
                    n = -n
                normals.append(n / (np.linalg.norm(n) or 1.0))
                centres.append(fc)
                faces.append(np.array(f) + off)
                base.append((rgb.redF(), rgb.greenF(), rgb.blueF()))
                edges.append(QColor(part.edge) if part.edge else None)
            verts.append(part.verts)
            if part.shadow:
                shadow.extend(range(off, off + len(part.verts)))
            off += len(part.verts)
        self._V = np.concatenate(verts)
        self._faces = faces
        self._n, self._c = np.array(normals), np.array(centres)
        self._base = np.array(base)
        self._edges = edges
        self._shadow = np.array(shadow)

    def scene(self) -> list[tuple[float, np.ndarray, QColor, QColor | None]]:
        """Visible faces as (depth, screen polygon, fill, edge), far first. Public for tests."""
        rot = rot_matrix(model_quat(self.q, self.toward_elbow))
        eye, basis = CAMERAS[self.view].basis()
        scr = _perspective((self._V @ rot.T - eye) @ basis.T, self.view)
        n, c = self._n @ rot.T, self._c @ rot.T
        visible = np.einsum("ij,ij->i", n, c - eye) < 0
        shade = 0.42 + 0.58 * np.clip(n @ _LIGHT, 0.0, None)
        rgb = np.clip(self._base * shade[:, None] * 1.15, 0.0, 1.0)
        depth = (c - eye) @ basis[2]
        idx = np.flatnonzero(visible)
        idx = idx[np.argsort(-depth[idx], kind="stable")]
        return [(float(depth[i]), scr[self._faces[i]], QColor.fromRgbF(*rgb[i]), self._edges[i]) for i in idx]

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        s = min(w / 2.6, h / 2.15)
        cx, cy = w / 2, h / 2

        def to_px(xy: np.ndarray) -> QPolygonF:
            return QPolygonF([QPointF(cx + x * s, cy - y * s) for x, y in xy])

        eye, basis = CAMERAS[self.view].basis()
        # ground grid
        p.setPen(QPen(QColor(theme.LINE_2), 1))
        segs = [((-2.0, y), (3.0, y)) for y in np.arange(-2.0, 2.01, 0.5)]
        segs += [((x, -2.0), (x, 2.0)) for x in np.arange(-2.0, 3.01, 0.5)]
        for a, b in segs:
            cam = (np.array([[a[0], a[1], _GROUND_Z], [b[0], b[1], _GROUND_Z]]) - eye) @ basis.T
            if (cam[:, 2] > 0.2).all():
                ln = to_px(_perspective(cam, self.view))
                p.drawLine(ln[0], ln[1])
        # shadow: the arm's vertices dropped onto the ground, convex hull filled
        rot = rot_matrix(model_quat(self.q, self.toward_elbow))
        pts = self._V[self._shadow] @ rot.T
        pts[:, 2] = _GROUND_Z
        cam = (pts - eye) @ basis.T
        if (cam[:, 2] > 0.2).all():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 120))
            p.drawPolygon(to_px(_hull(_perspective(cam, self.view))))
        # arm, back to front
        for _, poly, fill, edge in self.scene():
            p.setBrush(fill)
            p.setPen(QPen(edge, 0.8) if edge is not None else QPen(fill.darker(115), 0.6))
            p.drawPolygon(to_px(poly))
        p.end()


class Orientation3D(Panel):
    def __init__(self, parent=None) -> None:
        super().__init__("Orientation", parent)
        self.lbl_view = self.add_head(label("VIEW", "label"))
        self.cb_view = QComboBox()
        for v in VIEWS:
            self.cb_view.addItem(v.upper(), v)
        self.cb_view.currentIndexChanged.connect(self._on_view)
        self.add_head(self.cb_view)
        self.btn_flip = QPushButton("FLIP")
        self.btn_flip.setCheckable(True)
        self.btn_flip.setToolTip("Swap the hand and elbow ends of the model, if the sync didn't report\n"
                                 "which way the band is worn or the model points the wrong way")
        self.btn_flip.toggled.connect(lambda _on: self._apply_direction())
        self.add_head(self.btn_flip)
        self.canvas = ArmCanvas()
        self.body.addWidget(self.canvas, 1)
        self._on_view(0)
        self.hint = label("", "hint")
        self.hint.setWordWrap(True)
        self.body.addWidget(self.hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.S2); grid.setVerticalSpacing(theme.S_HALF)
        self.vals: dict[str, QLabel] = {}
        for col, (k, name) in enumerate((("roll", "ROLL"), ("pitch", "PITCH"), ("yaw", "YAW"))):
            v = label("—", "value")
            grid.addWidget(label(name, "caption"), 0, col); grid.addWidget(v, 1, col)
            self.vals[k] = v
        for col, k in enumerate(("x", "y", "z", "w")):
            c = label(k.upper(), "label")
            c.setStyleSheet(f"color: {theme.AXIS_COLORS[col]};")
            v = label("—", "value_sm")
            cell = QHBoxLayout(); cell.setSpacing(theme.S1)
            cell.addWidget(c); cell.addWidget(v, 1)
            grid.addLayout(cell, 2, col)
            self.vals[k] = v
        for col in range(4):
            grid.setColumnStretch(col, 1)
        grid.setAlignment(Qt.AlignBottom)
        self.body.addLayout(grid)
        self._q: Q.Quat = Q.IDENTITY
        self._euler = (0.0, 0.0, 0.0)
        self._synced_elbow: bool | None = None  # last x_direction reported by a sync
        self._has_origin = False
        self._apply_direction()
        self.update_quat(Q.IDENTITY, (0.0, 0.0, 0.0))

    # ------------------------------------------------------------------ controls
    @property
    def view(self) -> str:
        return self.canvas.view

    def set_view(self, view: str) -> None:
        i = self.cb_view.findData(view)
        if i >= 0:
            self.cb_view.setCurrentIndex(i)

    def _on_view(self, _i) -> None:
        self.canvas.view = self.cb_view.currentData()
        self.cb_view.setToolTip(VIEW_HELP[self.canvas.view])
        self.canvas.update()

    def set_arm(self, arm: str, x_direction: str) -> None:
        """arm: right/left/unknown; x_direction: wrist/elbow/unknown (kept until the next sync)."""
        self.canvas.set_arm(arm)
        if x_direction in ("wrist", "elbow"):
            self._synced_elbow = x_direction == "elbow"
        self._apply_direction()

    def reset_arm(self) -> None:
        self._synced_elbow = None
        self.canvas.set_arm("unknown")
        self._apply_direction()

    def set_has_origin(self, on: bool) -> None:
        if on != self._has_origin:
            self._has_origin = on
            self._apply_direction()

    def _apply_direction(self) -> None:
        elbow = bool(self._synced_elbow) != self.btn_flip.isChecked()
        self.canvas.toward_elbow = elbow
        if self._synced_elbow is None:
            band = "band direction: not synced yet"
        else:
            band = f"band +x → {'elbow' if self._synced_elbow else 'wrist'} (sync)"
        if self.btn_flip.isChecked():
            band += ", flipped"
        origin = "" if self._has_origin else " · point at the screen, press SET ORIGIN"
        self.hint.setText(band + origin)
        self.canvas.update()

    # ------------------------------------------------------------------ data
    def set_frame(self, frame) -> None:
        self._q = frame.quat
        self._euler = frame.euler

    def refresh(self) -> None:
        self.update_quat(self._q, self._euler)

    def update_quat(self, q: Q.Quat, euler) -> None:
        if q != self.canvas.q:
            self.canvas.q = q
            self.canvas.update()
        w, x, y, z = q
        for k, v in zip(("x", "y", "z", "w"), (x, y, z, w)):
            self.vals[k].setText(f"{v:+.3f}")
        for k, v in zip(("roll", "pitch", "yaw"), euler):
            self.vals[k].setText(f"{math.degrees(v):+6.1f}°")


__all__ = ["CAMERAS", "VIEWS", "ArmCanvas", "Orientation3D", "model_quat", "project", "rot_matrix"]
