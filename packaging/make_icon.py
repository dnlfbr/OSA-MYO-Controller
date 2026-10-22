"""Draw the app icon (a Myo armband: ring of 8 pods in perspective).

Near-black superellipse tile (#0A0A0A, 896 px at 64 px inset on a 1024 canvas,
radius 200) with a #2A2A2A hairline, line art stroked with the copper→amber→cyan spectrum, a blurred
glow underlay at 30 % opacity, round caps. No logos (the Thalmic mark is not reproduced).

    .venv/bin/python packaging/make_icon.py
writes packaging/icon/OSA-MYO-Controller.png (1024), packaging/OSA-MYO-Controller.icns and src/myo_bridge/gui/icon.png.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QBrush,
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "packaging" / "icon"

S = 1024
CX, CY = 512.0, 452.0
R_OUT, R_IN = 318.0, 214.0
TILT = 0.40          # vertical squash of the ring (perspective)
H = 120.0            # pod thickness (extrusion downwards)
N = 8
GAP = math.radians(7.0)

COPPER, AMBER, CYAN = QColor("#D98E5A"), QColor("#C8A050"), QColor("#4FB8C4")


def pt(r: float, a: float, dy: float = 0.0) -> QPointF:
    return QPointF(CX + r * math.cos(a), CY + r * TILT * math.sin(a) + dy)


def arc(r: float, a0: float, a1: float, dy: float = 0.0, steps: int = 18) -> list[QPointF]:
    return [pt(r, a0 + (a1 - a0) * i / steps, dy) for i in range(steps + 1)]


def spectrum() -> QLinearGradient:
    g = QLinearGradient(CX - R_OUT, CY - R_OUT * TILT, CX + R_OUT, CY + R_OUT * TILT + H)
    g.setColorAt(0.0, COPPER)
    g.setColorAt(0.5, AMBER)
    g.setColorAt(1.0, CYAN)
    return g


def visible(a0: float, a1: float, start: float) -> list[tuple[float, float]]:
    """Intersect [a0, a1] with the half-turns [start + 2πn, start + π + 2πn]."""
    out = []
    for n in range(-1, 3):
        lo, hi = max(a0, start + 2 * math.pi * n), min(a1, start + math.pi + 2 * math.pi * n)
        if hi - lo > 1e-3:
            out.append((lo, hi))
    return out


def pods() -> list[dict]:
    out = []
    for k in range(N):
        c = math.pi / 2 + k * 2 * math.pi / N  # k = 0 is the front (main) pod
        a0, a1 = c - math.pi / N + GAP / 2, c + math.pi / N - GAP / 2
        main = k == 0
        r_out = R_OUT + (14 if main else 0)
        top = QPolygonF(arc(r_out, a0, a1) + arc(R_IN, a1, a0))
        faces = []
        # outer wall faces the viewer where sin(a) > 0 (front half), the inner wall where sin(a) < 0
        for lo, hi in visible(a0, a1, 0.0):
            faces.append(QPolygonF(arc(r_out, lo, hi) + arc(r_out, hi, lo, H)))
        for lo, hi in visible(a0, a1, math.pi):
            faces.append(QPolygonF(arc(R_IN, lo, hi) + arc(R_IN, hi, lo, H)))
        out.append({"c": c, "top": top, "faces": faces, "main": main, "a": (a0, a1), "r": r_out})
    out.sort(key=lambda p: math.sin(p["c"]))  # back to front
    return out


def draw_art(p: QPainter, glow: bool) -> None:
    grad = spectrum()
    pen = QPen(QBrush(grad), 22 if glow else 9)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    # elastic band between pods: thin ellipse through the pod middles
    band = QPen(QBrush(grad), 10 if glow else 4)
    band.setCapStyle(Qt.RoundCap)
    p.setBrush(Qt.NoBrush)
    p.setPen(band)
    rm = (R_OUT + R_IN) / 2
    p.drawEllipse(QPointF(CX, CY + H * 0.55), rm, rm * TILT)
    for pod in pods():
        for f in pod["faces"]:
            p.setBrush(Qt.NoBrush if glow else QColor("#0E0E0E"))
            p.setPen(pen)
            p.drawPolygon(f)
        p.setBrush(Qt.NoBrush if glow else QColor("#161616"))
        p.setPen(pen)
        p.drawPolygon(pod["top"])
        if pod["main"]:
            # status LED bar on the main pod's outer wall
            a0, a1 = pod["a"]
            mid = (a0 + a1) / 2
            span = (a1 - a0) * 0.28
            led = QPen(COPPER, 26 if glow else 12)
            led.setCapStyle(Qt.RoundCap)
            p.setPen(led)
            path = QPainterPath()
            pts = arc(pod["r"], mid - span, mid + span, H * 0.5, 8)
            path.moveTo(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
            p.drawPath(path)


def blur(img: QImage, factor: int = 14) -> QImage:
    small = img.scaled(img.width() // factor, img.height() // factor, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small = small.scaled(img.width() // 4, img.height() // 4, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(img.width(), img.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def render() -> QImage:
    img = QImage(S, S, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(64, 64, 896, 896), 200, 200)
    p.fillPath(tile, QColor("#0A0A0A"))
    p.setPen(QPen(QColor("#2A2A2A"), 6))
    p.drawPath(tile)
    p.setClipPath(tile)

    glow = QImage(S, S, QImage.Format_ARGB32_Premultiplied)
    glow.fill(Qt.transparent)
    g = QPainter(glow)
    g.setRenderHint(QPainter.Antialiasing)
    draw_art(g, glow=True)
    g.end()
    p.setOpacity(0.30)
    p.drawImage(0, 0, blur(glow))
    p.setOpacity(1.0)
    draw_art(p, glow=False)
    p.end()
    return img


def main() -> int:
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    img = render()
    master = OUT_DIR / "OSA-MYO-Controller.png"
    img.save(str(master))
    img.scaled(512, 512, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(
        str(ROOT / "src" / "myo_bridge" / "gui" / "icon.png"))
    iconset = OUT_DIR / "OSA-MYO-Controller.iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = size * scale
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            img.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(iconset / name))
    if shutil.which("iconutil"):
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ROOT / "packaging" / "OSA-MYO-Controller.icns")],
                       check=True)
        shutil.rmtree(iconset)
    print("icon written:", master)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
