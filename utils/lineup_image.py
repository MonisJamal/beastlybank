"""
Clean & Minimal Matchday Starting 11 Lineup Image Generator.
Renders high-resolution broadcast-quality pitch graphics using Pillow.
"""
from __future__ import annotations

import io
import os
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from config import SUPPORTED_FORMATIONS, DEFAULT_FORMATION, POSITION_CATEGORIES


def get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Load the cleanest available sans-serif font across macOS, Linux, and container environments."""
    candidates = [
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        # Linux / Render / Debian / Ubuntu
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


# Complete, mathematically exact tactical coordinates for all 37 formations.
# Every single position is placed in its authentic football pitch position.
EXACT_FORMATION_COORDS: Dict[str, List[Tuple[str, float, float]]] = {
    # ── 3-Back ──
    "3-1-4-2": [
        ("GK", 0.50, 0.90),
        ("CB", 0.26, 0.78), ("CB", 0.50, 0.79), ("CB", 0.74, 0.78),
        ("CDM", 0.50, 0.64),
        ("LM", 0.14, 0.48), ("CM", 0.38, 0.48), ("CM", 0.62, 0.48), ("RM", 0.86, 0.48),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],
    "3-2-4-1": [
        ("GK", 0.50, 0.90),
        ("CB", 0.26, 0.78), ("CB", 0.50, 0.79), ("CB", 0.74, 0.78),
        ("CDM", 0.36, 0.64), ("CDM", 0.64, 0.64),
        ("LM", 0.14, 0.44), ("CAM", 0.38, 0.35), ("CAM", 0.62, 0.35), ("RM", 0.86, 0.44),
        ("ST", 0.50, 0.16),
    ],
    "3-4-1-2": [
        ("GK", 0.50, 0.90),
        ("CB", 0.26, 0.78), ("CB", 0.50, 0.79), ("CB", 0.74, 0.78),
        ("LM", 0.14, 0.52), ("CM", 0.38, 0.52), ("CM", 0.62, 0.52), ("RM", 0.86, 0.52),
        ("CAM", 0.50, 0.35),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],
    "3-4-2-1": [
        ("GK", 0.50, 0.90),
        ("CB", 0.26, 0.78), ("CB", 0.50, 0.79), ("CB", 0.74, 0.78),
        ("LM", 0.14, 0.52), ("CM", 0.38, 0.52), ("CM", 0.62, 0.52), ("RM", 0.86, 0.52),
        ("CF", 0.33, 0.32), ("CF", 0.67, 0.32),
        ("ST", 0.50, 0.16),
    ],
    "3-4-3 Diamond": [
        ("GK", 0.50, 0.90),
        ("CB", 0.26, 0.78), ("CB", 0.50, 0.79), ("CB", 0.74, 0.78),
        ("CDM", 0.50, 0.64),
        ("LM", 0.14, 0.48), ("RM", 0.86, 0.48),
        ("CAM", 0.50, 0.36),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.16), ("RW", 0.83, 0.22),
    ],
    "3-4-3 Flat": [
        ("GK", 0.50, 0.90),
        ("CB", 0.26, 0.78), ("CB", 0.50, 0.79), ("CB", 0.74, 0.78),
        ("LM", 0.14, 0.50), ("CM", 0.38, 0.50), ("CM", 0.62, 0.50), ("RM", 0.86, 0.50),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.16), ("RW", 0.83, 0.22),
    ],
    "3-5-1-1": [
        ("GK", 0.50, 0.90),
        ("CB", 0.26, 0.78), ("CB", 0.50, 0.79), ("CB", 0.74, 0.78),
        ("CDM", 0.50, 0.64),
        ("LM", 0.14, 0.48), ("CM", 0.38, 0.48), ("CM", 0.62, 0.48), ("RM", 0.86, 0.48),
        ("CAM", 0.50, 0.33),
        ("ST", 0.50, 0.16),
    ],
    "3-5-2": [
        ("GK", 0.50, 0.90),
        ("CB", 0.26, 0.78), ("CB", 0.50, 0.79), ("CB", 0.74, 0.78),
        ("LWB", 0.12, 0.56), ("CDM", 0.37, 0.64), ("CDM", 0.63, 0.64), ("RWB", 0.88, 0.56),
        ("CAM", 0.50, 0.36),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],

    # ── 4-Back ──
    "4-1-2-1-2 Narrow": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.64),
        ("CM", 0.34, 0.49), ("CM", 0.66, 0.49),
        ("CAM", 0.50, 0.35),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],
    "4-1-2-1-2 Wide": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.64),
        ("LM", 0.14, 0.46), ("RM", 0.86, 0.46),
        ("CAM", 0.50, 0.35),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],
    "4-1-3-2": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.64),
        ("LM", 0.14, 0.46), ("CM", 0.50, 0.46), ("RM", 0.86, 0.46),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],
    "4-1-3-2 Attacking": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.64),
        ("CAM", 0.24, 0.38), ("CAM", 0.50, 0.36), ("CAM", 0.76, 0.38),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],
    "4-1-4-1": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.64),
        ("LM", 0.14, 0.46), ("CM", 0.38, 0.46), ("CM", 0.62, 0.46), ("RM", 0.86, 0.46),
        ("ST", 0.50, 0.16),
    ],
    "4-2-2-2": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.36, 0.63), ("CDM", 0.64, 0.63),
        ("CAM", 0.26, 0.38), ("CAM", 0.74, 0.38),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],
    "4-2-3-1 Attack": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.36, 0.64), ("CDM", 0.64, 0.64),
        ("CAM", 0.24, 0.38), ("CAM", 0.50, 0.34), ("CAM", 0.76, 0.38),
        ("ST", 0.50, 0.16),
    ],
    "4-2-3-1 Narrow": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.36, 0.64), ("CDM", 0.64, 0.64),
        ("CAM", 0.26, 0.38), ("CAM", 0.50, 0.34), ("CAM", 0.74, 0.38),
        ("ST", 0.50, 0.16),
    ],
    "4-2-3-1 Wide": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.36, 0.64), ("CDM", 0.64, 0.64),
        ("LM", 0.14, 0.40), ("CAM", 0.50, 0.34), ("RM", 0.86, 0.40),
        ("ST", 0.50, 0.16),
    ],
    "4-2-4": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CM", 0.36, 0.50), ("CM", 0.64, 0.50),
        ("LW", 0.14, 0.22), ("ST", 0.38, 0.16), ("ST", 0.62, 0.16), ("RW", 0.86, 0.22),
    ],
    "4-3-1-2": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CM", 0.26, 0.52), ("CM", 0.50, 0.54), ("CM", 0.74, 0.52),
        ("CAM", 0.50, 0.35),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],
    "4-3-2-1": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CM", 0.26, 0.54), ("CM", 0.50, 0.56), ("CM", 0.74, 0.54),
        ("CF", 0.33, 0.32), ("CF", 0.67, 0.32),
        ("ST", 0.50, 0.16),
    ],
    "4-3-3 Attack": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CM", 0.34, 0.52), ("CM", 0.66, 0.52),
        ("CAM", 0.50, 0.36),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.16), ("RW", 0.83, 0.22),
    ],
    "4-3-3 Balanced": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CM", 0.26, 0.48), ("CM", 0.50, 0.50), ("CM", 0.74, 0.48),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.16), ("RW", 0.83, 0.22),
    ],
    "4-3-3 Defend": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.36, 0.63), ("CDM", 0.64, 0.63),
        ("CM", 0.50, 0.46),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.16), ("RW", 0.83, 0.22),
    ],
    "4-3-3 False 9": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.64),
        ("CM", 0.34, 0.48), ("CM", 0.66, 0.48),
        ("LW", 0.17, 0.22), ("CF", 0.50, 0.22), ("RW", 0.83, 0.22),
    ],
    "4-3-3 Flat": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CM", 0.26, 0.48), ("CM", 0.50, 0.48), ("CM", 0.74, 0.48),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.16), ("RW", 0.83, 0.22),
    ],
    "4-3-3 Holding": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.64),
        ("CM", 0.32, 0.46), ("CM", 0.68, 0.46),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.16), ("RW", 0.83, 0.22),
    ],
    "4-4-1-1 Attack": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("LM", 0.14, 0.48), ("CM", 0.38, 0.52), ("CM", 0.62, 0.52), ("RM", 0.86, 0.48),
        ("CAM", 0.50, 0.33),
        ("ST", 0.50, 0.16),
    ],
    "4-4-1-1 Midfield": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("LM", 0.14, 0.48), ("CM", 0.38, 0.48), ("CM", 0.62, 0.48), ("RM", 0.86, 0.48),
        ("CAM", 0.50, 0.32),
        ("ST", 0.50, 0.16),
    ],
    "4-4-2 Flat": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("LM", 0.14, 0.46), ("CM", 0.38, 0.46), ("CM", 0.62, 0.46), ("RM", 0.86, 0.46),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],
    "4-4-2 Holding": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("LM", 0.14, 0.48), ("CDM", 0.36, 0.62), ("CDM", 0.64, 0.62), ("RM", 0.86, 0.48),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],
    "4-5-1 Attack": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("LM", 0.14, 0.40), ("CM", 0.50, 0.56), ("CAM", 0.34, 0.36), ("CAM", 0.66, 0.36), ("RM", 0.86, 0.40),
        ("ST", 0.50, 0.16),
    ],
    "4-5-1 Flat": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("LM", 0.13, 0.46), ("CM", 0.31, 0.48), ("CM", 0.50, 0.48), ("CM", 0.69, 0.48), ("RM", 0.87, 0.46),
        ("ST", 0.50, 0.16),
    ],

    # ── 5-Back ──
    "5-2-1-2": [
        ("GK", 0.50, 0.90),
        ("LWB", 0.12, 0.68), ("CB", 0.31, 0.78), ("CB", 0.50, 0.79), ("CB", 0.69, 0.78), ("RWB", 0.88, 0.68),
        ("CM", 0.36, 0.50), ("CM", 0.64, 0.50),
        ("CAM", 0.50, 0.34),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],
    "5-2-3": [
        ("GK", 0.50, 0.90),
        ("LWB", 0.12, 0.68), ("CB", 0.31, 0.78), ("CB", 0.50, 0.79), ("CB", 0.69, 0.78), ("RWB", 0.88, 0.68),
        ("CM", 0.36, 0.48), ("CM", 0.64, 0.48),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.16), ("RW", 0.83, 0.22),
    ],
    "5-3-2": [
        ("GK", 0.50, 0.90),
        ("LWB", 0.12, 0.68), ("CB", 0.31, 0.78), ("CB", 0.50, 0.79), ("CB", 0.69, 0.78), ("RWB", 0.88, 0.68),
        ("CM", 0.28, 0.48), ("CM", 0.50, 0.48), ("CM", 0.72, 0.48),
        ("ST", 0.36, 0.16), ("ST", 0.64, 0.16),
    ],
    "5-4-1 Diamond": [
        ("GK", 0.50, 0.90),
        ("LWB", 0.12, 0.68), ("CB", 0.31, 0.78), ("CB", 0.50, 0.79), ("CB", 0.69, 0.78), ("RWB", 0.88, 0.68),
        ("CDM", 0.50, 0.60),
        ("LM", 0.15, 0.46), ("RM", 0.85, 0.46),
        ("CAM", 0.50, 0.33),
        ("ST", 0.50, 0.16),
    ],
    "5-4-1 Flat": [
        ("GK", 0.50, 0.90),
        ("LWB", 0.12, 0.68), ("CB", 0.31, 0.78), ("CB", 0.50, 0.79), ("CB", 0.69, 0.78), ("RWB", 0.88, 0.68),
        ("LM", 0.15, 0.48), ("CM", 0.38, 0.48), ("CM", 0.62, 0.48), ("RM", 0.85, 0.48),
        ("ST", 0.50, 0.16),
    ],
}


def compute_formation_coords(formation_name: str) -> List[Tuple[str, float, float]]:
    """Return the exact 11 tactical coordinates for the given formation."""
    if formation_name in EXACT_FORMATION_COORDS:
        return EXACT_FORMATION_COORDS[formation_name]

    # Try case-insensitive lookup
    for k, v in EXACT_FORMATION_COORDS.items():
        if k.lower() == formation_name.lower():
            return v

    return EXACT_FORMATION_COORDS[DEFAULT_FORMATION]


def draw_pitch_markings(draw: ImageDraw.ImageDraw, px0: int, py0: int, px1: int, py1: int) -> None:
    """Render minimal, attractive modern football pitch geometry."""
    pitch_w = px1 - px0
    pitch_h = py1 - py0
    center_x = px0 + pitch_w // 2
    mid_y = py0 + pitch_h // 2

    # Clean vibrant emerald lines
    line_color = "#34d399"

    # Outer pitch boundary
    draw.rectangle([px0 + 20, py0 + 20, px1 - 20, py1 - 20], outline=line_color, width=2)

    # Halfway line
    draw.line([(px0 + 20, mid_y), (px1 - 20, mid_y)], fill=line_color, width=2)

    # Center circle (r = 90 px) & center spot
    r_circle = 90
    draw.ellipse([center_x - r_circle, mid_y - r_circle, center_x + r_circle, mid_y + r_circle], outline=line_color, width=2)
    draw.ellipse([center_x - 4, mid_y - 4, center_x + 4, mid_y + 4], fill=line_color)

    # Attacking Penalty Area (Top)
    box_w = 400
    box_h = 170
    bx0 = center_x - box_w // 2
    bx1 = center_x + box_w // 2
    draw.rectangle([bx0, py0 + 20, bx1, py0 + 20 + box_h], outline=line_color, width=2)

    # Top 6-yard box
    s_box_w = 200
    s_box_h = 65
    draw.rectangle([center_x - s_box_w // 2, py0 + 20, center_x + s_box_w // 2, py0 + 20 + s_box_h], outline=line_color, width=2)

    # Defending Penalty Area (Bottom)
    draw.rectangle([bx0, py1 - 20 - box_h, bx1, py1 - 20], outline=line_color, width=2)

    # Bottom 6-yard box
    draw.rectangle([center_x - s_box_w // 2, py1 - 20 - s_box_h, center_x + s_box_w // 2, py1 - 20], outline=line_color, width=2)

    # Penalty spots
    draw.ellipse([center_x - 4, py0 + 20 + 120 - 4, center_x + 4, py0 + 20 + 120 + 4], fill=line_color)
    draw.ellipse([center_x - 4, py1 - 20 - 120 - 4, center_x + 4, py1 - 20 - 120 + 4], fill=line_color)

    # Corner arcs
    r_c = 20
    draw.arc([px0 + 20 - r_c, py0 + 20 - r_c, px0 + 20 + r_c, py0 + 20 + r_c], 0, 90, fill=line_color, width=2)
    draw.arc([px1 - 20 - r_c, py0 + 20 - r_c, px1 - 20 + r_c, py0 + 20 + r_c], 90, 180, fill=line_color, width=2)
    draw.arc([px0 + 20 - r_c, py1 - 20 - r_c, px0 + 20 + r_c, py1 - 20 + r_c], 270, 360, fill=line_color, width=2)
    draw.arc([px1 - 20 - r_c, py1 - 20 - r_c, px1 - 20 + r_c, py1 - 20 + r_c], 180, 270, fill=line_color, width=2)


def draw_player_badge(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    number: Optional[int],
    name: str,
    position: str,
    rating: Optional[int] = None,
    is_vacant: bool = False,
    font_num: Optional[ImageFont.ImageFont] = None,
    font_name: Optional[ImageFont.ImageFont] = None,
    font_pos: Optional[ImageFont.ImageFont] = None,
) -> None:
    """Draw a clean, minimalist yet attractive player jersey badge and name pill on the pitch."""
    if font_num is None:
        font_num = get_font(18, bold=True)
    if font_name is None:
        font_name = get_font(14, bold=True)
    if font_pos is None:
        font_pos = get_font(11, bold=True)

    r = 24
    if is_vacant:
        # Vacant slot with subtle outline
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#07110a", outline="#334155", width=2)
        draw.text((cx, cy), position, fill="#64748B", font=font_pos, anchor="mm")

        pill_w, pill_h = 110, 28
        p_x0 = cx - pill_w // 2
        p_y0 = cy + r + 4
        p_x1 = cx + pill_w // 2
        p_y1 = p_y0 + pill_h
        draw.rounded_rectangle([p_x0, p_y0, p_x1, p_y1], radius=6, fill="#070d0a", outline="#1e293b", width=1)
        draw.text((cx, p_y0 + pill_h // 2), "[Vacant]", fill="#64748B", font=font_pos, anchor="mm")
    else:
        # Occupied player slot with subtle glow halo and Beastly Gold ring
        draw.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], fill="#1e1b18")
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#0b131e", outline="#F59E0B", width=2)
        num_str = str(number) if number is not None else "-"
        draw.text((cx, cy), num_str, fill="#FFFFFF", font=font_num, anchor="mm")

        # Sleek Name & Position Pill
        pill_w, pill_h = 132, 36
        p_x0 = cx - pill_w // 2
        p_y0 = cy + r + 4
        p_x1 = cx + pill_w // 2
        p_y1 = p_y0 + pill_h

        draw.rounded_rectangle([p_x0, p_y0, p_x1, p_y1], radius=8, fill="#070d16", outline="#1e293b", width=1)

        # Truncate clean display name if needed
        disp_name = name[:13] + ".." if len(name) > 15 else name
        draw.text((cx, p_y0 + 11), disp_name, fill="#F8FAFC", font=font_name, anchor="mm")

        sub_info = f"{position}" + (f" • {rating}" if rating else "")
        draw.text((cx, p_y0 + 26), sub_info, fill="#38BDF8", font=font_pos, anchor="mm")


def assign_players_to_formation_slots(
    formation_slots: List[Tuple[str, float, float]],
    players: List[Dict[str, Any]],
) -> List[Optional[Dict[str, Any]]]:
    """
    Intelligently assign available squad players to tactical formation slots.
    Ensures goalkeepers stay in goal, defenders stay in defense, midfielders
    stay in midfield, and attackers stay up front.
    """
    available = list(players or [])
    used_ids = set()
    assignments: List[Optional[Dict[str, Any]]] = [None] * len(formation_slots)

    # Pass 1: Exact Match (player.position == slot_position)
    for idx, (slot_pos, _, _) in enumerate(formation_slots):
        for p in available:
            pid = p.get("id") or id(p)
            if pid not in used_ids and (p.get("position") or "").upper() == slot_pos.upper():
                assignments[idx] = p
                used_ids.add(pid)
                break

    # Pass 2: Alternate Positions (alt_positions declared on player profile)
    for idx, (slot_pos, _, _) in enumerate(formation_slots):
        if assignments[idx] is not None:
            continue
        for p in available:
            pid = p.get("id") or id(p)
            if pid in used_ids:
                continue
            alts = [
                a.strip().upper()
                for a in (p.get("alt_positions") or "").replace(";", ",").replace("/", ",").split(",")
                if a.strip()
            ]
            if slot_pos.upper() in alts:
                assignments[idx] = p
                used_ids.add(pid)
                break

    # Pass 3: Close Tactical Match
    close_pairs = {
        "LB": ["LWB", "CB"],
        "RB": ["RWB", "CB"],
        "LWB": ["LB", "LM"],
        "RWB": ["RB", "RM"],
        "CB": ["LB", "RB", "LWB", "RWB"],
        "CDM": ["CM"],
        "CM": ["CDM", "CAM", "LM", "RM"],
        "CAM": ["CM", "CF"],
        "LM": ["LW", "LWB", "CM"],
        "RM": ["RW", "RWB", "CM"],
        "LW": ["LM", "ST", "CF"],
        "RW": ["RM", "ST", "CF"],
        "CF": ["ST", "CAM", "LW", "RW"],
        "ST": ["CF", "LW", "RW"],
    }
    for idx, (slot_pos, _, _) in enumerate(formation_slots):
        if assignments[idx] is not None:
            continue
        valid_subs = close_pairs.get(slot_pos.upper(), [])
        for p in available:
            pid = p.get("id") or id(p)
            if pid in used_ids:
                continue
            pos = (p.get("position") or "").upper()
            if pos in valid_subs:
                assignments[idx] = p
                used_ids.add(pid)
                break

    # Pass 4: Same Category Match (Goalkeeper, Defense, Midfield, Attack)
    for idx, (slot_pos, _, _) in enumerate(formation_slots):
        if assignments[idx] is not None:
            continue
        slot_cat = POSITION_CATEGORIES.get(slot_pos.upper())
        for p in available:
            pid = p.get("id") or id(p)
            if pid in used_ids:
                continue
            pos = (p.get("position") or "").upper()
            if POSITION_CATEGORIES.get(pos) == slot_cat:
                assignments[idx] = p
                used_ids.add(pid)
                break

    # Pass 5: Fallback for any remaining unassigned players
    for idx in range(len(formation_slots)):
        if assignments[idx] is None:
            for p in available:
                pid = p.get("id") or id(p)
                if pid not in used_ids:
                    assignments[idx] = p
                    used_ids.add(pid)
                    break

    return assignments


def generate_lineup_image(
    team_name: str,
    manager_name: str,
    formation_name: str,
    starting_players: Optional[List[Dict[str, Any]]] = None,
) -> io.BytesIO:
    """
    Generate a clean, minimal yet attractive Starting 11 Matchday Pitch graphic.
    Completely excludes the bench to focus exclusively on the pitch lineup.
    Returns in-memory PNG BytesIO buffer.
    """
    width, height = 1080, 1440
    img = Image.new("RGB", (width, height), color="#07110a")
    draw = ImageDraw.Draw(img)

    # Load typography
    font_sub = get_font(18, bold=False)
    font_num = get_font(18, bold=True)
    font_name = get_font(14, bold=True)
    font_pos = get_font(11, bold=True)

    # Dynamic team name sizing
    clean_team = team_name.strip().upper()
    team_font_size = 36 if len(clean_team) <= 22 else (28 if len(clean_team) <= 32 else 22)
    font_team = get_font(team_font_size, bold=True)

    # 1. Clean Minimalist Header Banner
    draw.text((width // 2, 52), clean_team, fill="#F8FAFC", font=font_team, anchor="mm")
    sub_text = f"MANAGER: {manager_name.strip()}   |   FORMATION: {formation_name.strip()}"
    draw.text((width // 2, 98), sub_text, fill="#94A3B8", font=font_sub, anchor="mm")

    # Hairline divider
    draw.line([(60, 138), (width - 60, 138)], fill="#1A3826", width=2)

    # 2. Football Pitch Dimensions
    px0, py0, px1, py1 = 40, 155, width - 40, height - 35
    pitch_w = px1 - px0
    pitch_h = py1 - py0

    # Draw pitch grass bands
    n_stripes = 12
    stripe_h = pitch_h / n_stripes
    for i in range(n_stripes):
        sy0 = py0 + i * stripe_h
        sy1 = sy0 + stripe_h
        col = "#0b2316" if i % 2 == 0 else "#0e2b1b"
        draw.rectangle([px0, sy0, px1, sy1], fill=col)

    # Outer pitch border
    draw.rectangle([px0, py0, px1, py1], outline="#1a4329", width=3)

    # Draw pitch lines & penalty areas
    draw_pitch_markings(draw, px0, py0, px1, py1)

    # 3. Compute Coordinates for 11 Positions
    formation_slots = compute_formation_coords(formation_name)

    # 4. Intelligently match starting players to formation slots
    slot_assignments = assign_players_to_formation_slots(formation_slots, starting_players or [])

    # 5. Render 11 Player Badges on the Pitch
    for slot_idx, (pos_tag, norm_x, norm_y) in enumerate(formation_slots):
        cx = int(px0 + norm_x * pitch_w)
        cy = int(py0 + norm_y * pitch_h)
        player = slot_assignments[slot_idx]

        if player:
            name = player.get("player_name") or f"Player {slot_idx+1}"
            number = player.get("number")
            rating = player.get("rating")
            pos = player.get("position") or pos_tag
            draw_player_badge(
                draw=draw,
                cx=cx,
                cy=cy,
                number=number,
                name=name,
                position=pos,
                rating=rating,
                is_vacant=False,
                font_num=font_num,
                font_name=font_name,
                font_pos=font_pos,
            )
        else:
            draw_player_badge(
                draw=draw,
                cx=cx,
                cy=cy,
                number=None,
                name="[Vacant]",
                position=pos_tag,
                rating=None,
                is_vacant=True,
                font_num=font_num,
                font_name=font_name,
                font_pos=font_pos,
            )

    # 6. Export to in-memory BytesIO buffer
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
