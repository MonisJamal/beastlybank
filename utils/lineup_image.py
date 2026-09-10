"""
Adaptive Matchday Starting 11 & Squad Lineup Card Generator.
Renders broadcast-quality matchday program graphics inspired by classic football posters.
Dynamically adapts kit colors, GK kits, mascots, crests, slogans, and chants
to any mentioned world club or custom user-created club.
"""
from __future__ import annotations

import io
import math
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
EXACT_FORMATION_COORDS: Dict[str, List[Tuple[str, float, float]]] = {
    # ── 3-Back ──
    "3-1-4-2": [
        ("GK", 0.50, 0.90),
        ("CB", 0.24, 0.77), ("CB", 0.50, 0.78), ("CB", 0.76, 0.77),
        ("CDM", 0.50, 0.63),
        ("LM", 0.13, 0.48), ("CM", 0.38, 0.48), ("CM", 0.62, 0.48), ("RM", 0.87, 0.48),
        ("ST", 0.36, 0.15), ("ST", 0.64, 0.15),
    ],
    "3-2-4-1": [
        ("GK", 0.50, 0.90),
        ("CB", 0.24, 0.77), ("CB", 0.50, 0.78), ("CB", 0.76, 0.77),
        ("CDM", 0.36, 0.63), ("CDM", 0.64, 0.63),
        ("LM", 0.13, 0.44), ("CAM", 0.38, 0.35), ("CAM", 0.62, 0.35), ("RM", 0.87, 0.44),
        ("ST", 0.50, 0.15),
    ],
    "3-4-1-2": [
        ("GK", 0.50, 0.90),
        ("CB", 0.24, 0.77), ("CB", 0.50, 0.78), ("CB", 0.76, 0.77),
        ("LM", 0.13, 0.52), ("CM", 0.38, 0.52), ("CM", 0.62, 0.52), ("RM", 0.87, 0.52),
        ("CAM", 0.50, 0.35),
        ("ST", 0.36, 0.15), ("ST", 0.64, 0.15),
    ],
    "3-4-2-1": [
        ("GK", 0.50, 0.90),
        ("CB", 0.24, 0.77), ("CB", 0.50, 0.78), ("CB", 0.76, 0.77),
        ("LM", 0.13, 0.52), ("CM", 0.38, 0.52), ("CM", 0.62, 0.52), ("RM", 0.87, 0.52),
        ("CAM", 0.34, 0.32), ("CAM", 0.66, 0.32),
        ("ST", 0.50, 0.15),
    ],
    "3-4-3 Diamond": [
        ("GK", 0.50, 0.90),
        ("CB", 0.24, 0.77), ("CB", 0.50, 0.78), ("CB", 0.76, 0.77),
        ("CDM", 0.50, 0.63),
        ("LM", 0.13, 0.48), ("RM", 0.87, 0.48),
        ("CAM", 0.50, 0.35),
        ("LW", 0.18, 0.20), ("ST", 0.50, 0.15), ("RW", 0.82, 0.20),
    ],
    "3-4-3 Flat": [
        ("GK", 0.50, 0.90),
        ("CB", 0.24, 0.77), ("CB", 0.50, 0.78), ("CB", 0.76, 0.77),
        ("LM", 0.13, 0.48), ("CM", 0.38, 0.48), ("CM", 0.62, 0.48), ("RM", 0.87, 0.48),
        ("LW", 0.18, 0.20), ("ST", 0.50, 0.15), ("RW", 0.82, 0.20),
    ],
    "3-5-1-1": [
        ("GK", 0.50, 0.90),
        ("CB", 0.24, 0.77), ("CB", 0.50, 0.78), ("CB", 0.76, 0.77),
        ("CDM", 0.36, 0.63), ("CDM", 0.64, 0.63),
        ("LM", 0.13, 0.48), ("CM", 0.50, 0.48), ("RM", 0.87, 0.48),
        ("CF", 0.50, 0.32),
        ("ST", 0.50, 0.15),
    ],
    "3-5-2": [
        ("GK", 0.50, 0.90),
        ("CB", 0.24, 0.77), ("CB", 0.50, 0.78), ("CB", 0.76, 0.77),
        ("CDM", 0.36, 0.64), ("CDM", 0.64, 0.64),
        ("LM", 0.13, 0.48), ("CAM", 0.50, 0.36), ("RM", 0.87, 0.48),
        ("ST", 0.36, 0.15), ("ST", 0.64, 0.15),
    ],

    # ── 4-Back ──
    "4-1-2-1-2 Narrow": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.63),
        ("CM", 0.32, 0.48), ("CM", 0.68, 0.48),
        ("CAM", 0.50, 0.33),
        ("ST", 0.36, 0.15), ("ST", 0.64, 0.15),
    ],
    "4-1-2-1-2 Wide": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.63),
        ("LM", 0.14, 0.46), ("RM", 0.86, 0.46),
        ("CAM", 0.50, 0.33),
        ("ST", 0.36, 0.15), ("ST", 0.64, 0.15),
    ],
    "4-1-3-2": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.63),
        ("LM", 0.14, 0.45), ("CM", 0.50, 0.45), ("RM", 0.86, 0.45),
        ("ST", 0.36, 0.15), ("ST", 0.64, 0.15),
    ],
    "4-1-4-1": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.63),
        ("LM", 0.14, 0.44), ("CM", 0.38, 0.44), ("CM", 0.62, 0.44), ("RM", 0.86, 0.44),
        ("ST", 0.50, 0.15),
    ],
    "4-2-1-3": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.36, 0.63), ("CDM", 0.64, 0.63),
        ("CAM", 0.50, 0.42),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.15), ("RW", 0.83, 0.22),
    ],
    "4-2-1-3 Attack": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.36, 0.63), ("CDM", 0.64, 0.63),
        ("CAM", 0.50, 0.42),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.15), ("RW", 0.83, 0.22),
    ],
    "4-2-2-2": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.36, 0.63), ("CDM", 0.64, 0.63),
        ("CAM", 0.28, 0.40), ("CAM", 0.72, 0.40),
        ("ST", 0.36, 0.15), ("ST", 0.64, 0.15),
    ],
    "4-2-3-1 Narrow": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.36, 0.63), ("CDM", 0.64, 0.63),
        ("CAM", 0.26, 0.38), ("CAM", 0.50, 0.35), ("CAM", 0.74, 0.38),
        ("ST", 0.50, 0.15),
    ],
    "4-2-3-1 Wide": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.36, 0.63), ("CDM", 0.64, 0.63),
        ("LM", 0.14, 0.42), ("CAM", 0.50, 0.36), ("RM", 0.86, 0.42),
        ("ST", 0.50, 0.15),
    ],
    "4-2-4": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CM", 0.36, 0.52), ("CM", 0.64, 0.52),
        ("LW", 0.16, 0.22), ("ST", 0.38, 0.15), ("ST", 0.62, 0.15), ("RW", 0.84, 0.22),
    ],
    "4-3-1-2": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CM", 0.26, 0.52), ("CM", 0.50, 0.54), ("CM", 0.74, 0.52),
        ("CAM", 0.50, 0.34),
        ("ST", 0.36, 0.15), ("ST", 0.64, 0.15),
    ],
    "4-3-2-1": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CM", 0.26, 0.54), ("CM", 0.50, 0.56), ("CM", 0.74, 0.54),
        ("CAM", 0.35, 0.34), ("CAM", 0.65, 0.34),
        ("ST", 0.50, 0.15),
    ],
    "4-3-3 Attack": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CM", 0.34, 0.54), ("CM", 0.66, 0.54),
        ("CAM", 0.50, 0.38),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.15), ("RW", 0.83, 0.22),
    ],
    "4-3-3 Balanced": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CM", 0.28, 0.50), ("CM", 0.50, 0.52), ("CM", 0.72, 0.50),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.15), ("RW", 0.83, 0.22),
    ],
    "4-3-3 Defend": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.36, 0.63), ("CDM", 0.64, 0.63),
        ("CM", 0.50, 0.44),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.15), ("RW", 0.83, 0.22),
    ],
    "4-3-3 False 9": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.63),
        ("CM", 0.32, 0.48), ("CM", 0.68, 0.48),
        ("LW", 0.17, 0.20), ("CF", 0.50, 0.25), ("RW", 0.83, 0.20),
    ],
    "4-3-3 Holding": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("CDM", 0.50, 0.63),
        ("CM", 0.32, 0.46), ("CM", 0.68, 0.46),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.15), ("RW", 0.83, 0.22),
    ],
    "4-4-1-1 Attack": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("LM", 0.14, 0.48), ("CM", 0.38, 0.52), ("CM", 0.62, 0.52), ("RM", 0.86, 0.48),
        ("CAM", 0.50, 0.33),
        ("ST", 0.50, 0.15),
    ],
    "4-4-1-1 Midfield": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("LM", 0.14, 0.48), ("CM", 0.38, 0.48), ("CM", 0.62, 0.48), ("RM", 0.86, 0.48),
        ("CAM", 0.50, 0.32),
        ("ST", 0.50, 0.15),
    ],
    "4-4-2 Flat": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("LM", 0.14, 0.46), ("CM", 0.38, 0.46), ("CM", 0.62, 0.46), ("RM", 0.86, 0.46),
        ("ST", 0.36, 0.15), ("ST", 0.64, 0.15),
    ],
    "4-4-2 Holding": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("LM", 0.14, 0.48), ("CDM", 0.36, 0.62), ("CDM", 0.64, 0.62), ("RM", 0.86, 0.48),
        ("ST", 0.36, 0.15), ("ST", 0.64, 0.15),
    ],
    "4-5-1 Attack": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("LM", 0.14, 0.40), ("CM", 0.50, 0.56), ("CAM", 0.34, 0.36), ("CAM", 0.66, 0.36), ("RM", 0.86, 0.40),
        ("ST", 0.50, 0.15),
    ],
    "4-5-1 Flat": [
        ("GK", 0.50, 0.90),
        ("LB", 0.14, 0.75), ("CB", 0.38, 0.78), ("CB", 0.62, 0.78), ("RB", 0.86, 0.75),
        ("LM", 0.13, 0.46), ("CM", 0.31, 0.48), ("CM", 0.50, 0.48), ("CM", 0.69, 0.48), ("RM", 0.87, 0.46),
        ("ST", 0.50, 0.15),
    ],

    # ── 5-Back ──
    "5-2-1-2": [
        ("GK", 0.50, 0.90),
        ("LWB", 0.12, 0.68), ("CB", 0.31, 0.78), ("CB", 0.50, 0.79), ("CB", 0.69, 0.78), ("RWB", 0.88, 0.68),
        ("CM", 0.36, 0.50), ("CM", 0.64, 0.50),
        ("CAM", 0.50, 0.34),
        ("ST", 0.36, 0.15), ("ST", 0.64, 0.15),
    ],
    "5-2-3": [
        ("GK", 0.50, 0.90),
        ("LWB", 0.12, 0.68), ("CB", 0.31, 0.78), ("CB", 0.50, 0.79), ("CB", 0.69, 0.78), ("RWB", 0.88, 0.68),
        ("CM", 0.36, 0.48), ("CM", 0.64, 0.48),
        ("LW", 0.17, 0.22), ("ST", 0.50, 0.15), ("RW", 0.83, 0.22),
    ],
    "5-3-2": [
        ("GK", 0.50, 0.90),
        ("LWB", 0.12, 0.68), ("CB", 0.31, 0.78), ("CB", 0.50, 0.79), ("CB", 0.69, 0.78), ("RWB", 0.88, 0.68),
        ("CM", 0.28, 0.48), ("CM", 0.50, 0.48), ("CM", 0.72, 0.48),
        ("ST", 0.36, 0.15), ("ST", 0.64, 0.15),
    ],
    "5-4-1 Diamond": [
        ("GK", 0.50, 0.90),
        ("LWB", 0.12, 0.68), ("CB", 0.31, 0.78), ("CB", 0.50, 0.79), ("CB", 0.69, 0.78), ("RWB", 0.88, 0.68),
        ("CDM", 0.50, 0.60),
        ("LM", 0.15, 0.46), ("RM", 0.85, 0.46),
        ("CAM", 0.50, 0.33),
        ("ST", 0.50, 0.15),
    ],
    "5-4-1 Flat": [
        ("GK", 0.50, 0.90),
        ("LWB", 0.12, 0.68), ("CB", 0.31, 0.78), ("CB", 0.50, 0.79), ("CB", 0.69, 0.78), ("RWB", 0.88, 0.68),
        ("LM", 0.15, 0.48), ("CM", 0.38, 0.48), ("CM", 0.62, 0.48), ("RM", 0.85, 0.48),
        ("ST", 0.50, 0.15),
    ],
}


# ==============================================================================
# Comprehensive Global Club Brand Registry
# ==============================================================================
CLUB_PRESETS: Dict[str, Dict[str, Any]] = {
    "manchester united": {
        "display_name": "MANCHESTER UNITED",
        "primary": "#DA291C",
        "secondary": "#FFFFFF",
        "dark": "#0F172A",
        "gk_primary": "#18181B",
        "gk_secondary": "#FFFFFF",
        "accent": "#C70101",
        "slogan_1": "LEAD. ADAPT. WIN.",
        "slogan_2": "UNITED IS THE WAY.",
        "chant": "GLORY GLORY MAN UNITED.",
        "mascot": "devil",
    },
    "real madrid": {
        "display_name": "REAL MADRID",
        "primary": "#FFFFFF",
        "secondary": "#00529F",
        "dark": "#0F172A",
        "border_kit": "#00529F",
        "gk_primary": "#EE9A00",
        "gk_secondary": "#000000",
        "accent": "#00529F",
        "slogan_1": "THE KINGS OF EUROPE.",
        "slogan_2": "¡HALA MADRID Y NADA MÁS!",
        "chant": "HISTORIA QUE TÚ HICISTE, HISTORIA POR HACER.",
        "mascot": "crown",
    },
    "barcelona": {
        "display_name": "FC BARCELONA",
        "primary": "#A50044",
        "secondary": "#EDBB00",
        "dark": "#004D98",
        "gk_primary": "#004D98",
        "gk_secondary": "#EDBB00",
        "accent": "#004D98",
        "slogan_1": "MORE THAN A CLUB.",
        "slogan_2": "MÉS QUE UN CLUB.",
        "chant": "TOTS UNITS FEM FORÇA - FORÇA BARÇA!",
        "mascot": "star",
    },
    "arsenal": {
        "display_name": "ARSENAL FC",
        "primary": "#EF0107",
        "secondary": "#FFFFFF",
        "dark": "#023474",
        "gk_primary": "#023474",
        "gk_secondary": "#FFFFFF",
        "accent": "#EF0107",
        "slogan_1": "VICTORIA CONCORDIA CRESCIT.",
        "slogan_2": "NORTH LONDON IS RED.",
        "chant": "COME ON YOU GUNNERS!",
        "mascot": "cannon",
    },
    "liverpool": {
        "display_name": "LIVERPOOL FC",
        "primary": "#C8102E",
        "secondary": "#FFFFFF",
        "dark": "#00B2A9",
        "gk_primary": "#18181B",
        "gk_secondary": "#FFFFFF",
        "accent": "#C8102E",
        "slogan_1": "THIS IS ANFIELD.",
        "slogan_2": "WE ARE LIVERPOOL.",
        "chant": "YOU'LL NEVER WALK ALONE.",
        "mascot": "bird",
    },
    "chelsea": {
        "display_name": "CHELSEA FC",
        "primary": "#034694",
        "secondary": "#FFFFFF",
        "dark": "#DBA111",
        "gk_primary": "#EE9A00",
        "gk_secondary": "#000000",
        "accent": "#034694",
        "slogan_1": "PRIDE OF LONDON.",
        "slogan_2": "BLUE IS THE COLOUR.",
        "chant": "CARE FREE, WHEREVER YOU MAY BE.",
        "mascot": "lion",
    },
    "manchester city": {
        "display_name": "MANCHESTER CITY",
        "primary": "#6CABDD",
        "secondary": "#1C2C5B",
        "dark": "#1C2C5B",
        "gk_primary": "#1C2C5B",
        "gk_secondary": "#FFFFFF",
        "accent": "#6CABDD",
        "slogan_1": "SUPERBIA IN PROELIO.",
        "slogan_2": "THIS IS OUR CITY.",
        "chant": "BLUE MOON, YOU SAW ME STANDING ALONE.",
        "mascot": "ship",
    },
    "tottenham": {
        "display_name": "TOTTENHAM HOTSPUR",
        "primary": "#FFFFFF",
        "secondary": "#132257",
        "dark": "#132257",
        "border_kit": "#132257",
        "gk_primary": "#FDB913",
        "gk_secondary": "#132257",
        "accent": "#132257",
        "slogan_1": "TO DARE IS TO DO.",
        "slogan_2": "COME ON YOU SPURS.",
        "chant": "GLORY GLORY TOTTENHAM HOTSPUR.",
        "mascot": "bird",
    },
    "bayern munich": {
        "display_name": "FC BAYERN MÜNCHEN",
        "primary": "#DC052D",
        "secondary": "#FFFFFF",
        "dark": "#0066B2",
        "gk_primary": "#18181B",
        "gk_secondary": "#FFFFFF",
        "accent": "#DC052D",
        "slogan_1": "STERN DES SÜDENS.",
        "slogan_2": "MIA SAN MIA.",
        "chant": "FC BAYERN, FOREVER NUMBER ONE!",
        "mascot": "star",
    },
    "borussia dortmund": {
        "display_name": "BORUSSIA DORTMUND",
        "primary": "#FDE100",
        "secondary": "#000000",
        "dark": "#000000",
        "gk_primary": "#334155",
        "gk_secondary": "#FDE100",
        "accent": "#FDE100",
        "slogan_1": "ECHTE LIEBE.",
        "slogan_2": "YELLOW WALL FOREVER.",
        "chant": "HEJA BVB, HEJA BVB!",
        "mascot": "star",
    },
    "bayer leverkusen": {
        "display_name": "BAYER 04 LEVERKUSEN",
        "primary": "#E32221",
        "secondary": "#FFFFFF",
        "dark": "#000000",
        "gk_primary": "#000000",
        "gk_secondary": "#FFFFFF",
        "accent": "#E32221",
        "slogan_1": "WERKSELF INVICTUS.",
        "slogan_2": "DIE WERKSELF SIEGT.",
        "chant": "LEVERKUSEN, UNSER LEBEN!",
        "mascot": "lion",
    },
    "paris saint-germain": {
        "display_name": "PARIS SAINT-GERMAIN",
        "primary": "#004170",
        "secondary": "#DA291C",
        "dark": "#004170",
        "gk_primary": "#00965E",
        "gk_secondary": "#FFFFFF",
        "accent": "#DA291C",
        "slogan_1": "ICI C'EST PARIS.",
        "slogan_2": "PARIS EST MAGIQUE.",
        "chant": "ALLEZ PARIS SAINT-GERMAIN!",
        "mascot": "crest",
    },
    "juventus": {
        "display_name": "JUVENTUS FC",
        "primary": "#000000",
        "secondary": "#FFFFFF",
        "dark": "#000000",
        "border_kit": "#FFFFFF",
        "gk_primary": "#E25822",
        "gk_secondary": "#000000",
        "accent": "#000000",
        "slogan_1": "FINO ALLA FINE.",
        "slogan_2": "FORZA JUVE.",
        "chant": "JUVENTUS, STORIA DI UN GRANDE AMORE.",
        "mascot": "star",
    },
    "ac milan": {
        "display_name": "AC MILAN",
        "primary": "#AC1B24",
        "secondary": "#000000",
        "dark": "#000000",
        "gk_primary": "#008844",
        "gk_secondary": "#FFFFFF",
        "accent": "#AC1B24",
        "slogan_1": "SEMPRE MILAN.",
        "slogan_2": "ROSSONERI NEL CUORE.",
        "chant": "FORZA LOTTA VINCERAI!",
        "mascot": "devil",
    },
    "inter milan": {
        "display_name": "INTER MILANO",
        "primary": "#0068A8",
        "secondary": "#000000",
        "dark": "#000000",
        "gk_primary": "#E25822",
        "gk_secondary": "#000000",
        "accent": "#0068A8",
        "slogan_1": "NOT FOR EVERYONE.",
        "slogan_2": "FORZA INTER.",
        "chant": "C'È SOLO L'INTER, PER SEMPRE.",
        "mascot": "star",
    },
    "atletico madrid": {
        "display_name": "ATLÉTICO DE MADRID",
        "primary": "#CB3524",
        "secondary": "#FFFFFF",
        "dark": "#1A2B4C",
        "gk_primary": "#1A2B4C",
        "gk_secondary": "#FFFFFF",
        "accent": "#CB3524",
        "slogan_1": "CORAJE Y CORAZÓN.",
        "slogan_2": "NUNCA DEJJES DE CREER.",
        "chant": "AÚPA ATLETI, SIEMPRE ADELANTE!",
        "mascot": "crest",
    },
    "napoli": {
        "display_name": "SSC NAPOLI",
        "primary": "#12A0D7",
        "secondary": "#FFFFFF",
        "dark": "#0B3054",
        "gk_primary": "#18181B",
        "gk_secondary": "#FFFFFF",
        "accent": "#12A0D7",
        "slogan_1": "FORZA NAPOLI SEMPRE.",
        "slogan_2": "VESUVIO NEL CUORE.",
        "chant": "UN GIORNO ALL'IMPROVVISO!",
        "mascot": "crest",
    },
    "aston villa": {
        "display_name": "ASTON VILLA FC",
        "primary": "#670E36",
        "secondary": "#95BFE5",
        "dark": "#670E36",
        "gk_primary": "#EAA322",
        "gk_secondary": "#000000",
        "accent": "#670E36",
        "slogan_1": "PREPARED.",
        "slogan_2": "UP THE VILLA.",
        "chant": "VILLA, VILLA, WE LOVE THE VILLA!",
        "mascot": "lion",
    },
    "newcastle": {
        "display_name": "NEWCASTLE UNITED",
        "primary": "#000000",
        "secondary": "#FFFFFF",
        "dark": "#000000",
        "border_kit": "#000000",
        "gk_primary": "#E25822",
        "gk_secondary": "#000000",
        "accent": "#000000",
        "slogan_1": "HOWAY THE LADS.",
        "slogan_2": "GEORDIE NATION.",
        "chant": "TOON TOON, BLACK AND WHITE ARMY!",
        "mascot": "crest",
    },
    "ajax": {
        "display_name": "AFC AJAX",
        "primary": "#D2122E",
        "secondary": "#FFFFFF",
        "dark": "#000000",
        "gk_primary": "#18181B",
        "gk_secondary": "#FFFFFF",
        "accent": "#D2122E",
        "slogan_1": "WIJ ZIJN AJAX.",
        "slogan_2": "DE BESTE VAN DE STAD.",
        "chant": "AJAX AMSTERDAM FOREVER!",
        "mascot": "crest",
    },
    "benfica": {
        "display_name": "SL BENFICA",
        "primary": "#E21B23",
        "secondary": "#FFFFFF",
        "dark": "#1E293B",
        "gk_primary": "#18181B",
        "gk_secondary": "#FFFFFF",
        "accent": "#E21B23",
        "slogan_1": "E PLURIBUS UNUM.",
        "slogan_2": "O GLORIOSO SLB.",
        "chant": "EU AMO O BENFICA!",
        "mascot": "bird",
    },
    "sporting cp": {
        "display_name": "SPORTING CP",
        "primary": "#008050",
        "secondary": "#FFFFFF",
        "dark": "#1E293B",
        "gk_primary": "#18181B",
        "gk_secondary": "#FFFFFF",
        "accent": "#008050",
        "slogan_1": "ESFORÇO, DEDICAÇÃO, DEVOÇÃO E GLÓRIA.",
        "slogan_2": "ONDE VAI UM, VÃO TODOS.",
        "chant": "VIVA O SPORTING CLUBE DE PORTUGAL!",
        "mascot": "lion",
    },
    "porto": {
        "display_name": "FC PORTO",
        "primary": "#003882",
        "secondary": "#FFFFFF",
        "dark": "#003882",
        "gk_primary": "#E25822",
        "gk_secondary": "#000000",
        "accent": "#003882",
        "slogan_1": "SOMOS PORTO.",
        "slogan_2": "A VITÓRIA É O NOSSO DESTINO.",
        "chant": "FORÇA PORTO, ALLEZ!",
        "mascot": "dragon",
    },
    "beastly": {
        "display_name": "BEASTLY FC",
        "primary": "#F59E0B",
        "secondary": "#07110A",
        "dark": "#07110A",
        "gk_primary": "#10B981",
        "gk_secondary": "#07110A",
        "accent": "#F59E0B",
        "slogan_1": "DOMINATE. EMPOWER. CONQUER.",
        "slogan_2": "THE BEAST OF THE PITCH.",
        "chant": "BEASTLY BANK - UNSTOPPABLE DYNASTY!",
        "mascot": "crest",
    },
}

# Club alias mappings for robust detection
CLUB_ALIASES: Dict[str, str] = {
    "mufc": "manchester united",
    "man utd": "manchester united",
    "man united": "manchester united",
    "united": "manchester united",
    "rma": "real madrid",
    "madrid": "real madrid",
    "los blancos": "real madrid",
    "barca": "barcelona",
    "barça": "barcelona",
    "fcb": "barcelona",
    "blaugrana": "barcelona",
    "afc": "arsenal",
    "gunners": "arsenal",
    "lfc": "liverpool",
    "reds": "liverpool",
    "cfc": "chelsea",
    "blues": "chelsea",
    "mcfc": "manchester city",
    "man city": "manchester city",
    "city": "manchester city",
    "spurs": "tottenham",
    "thfc": "tottenham",
    "bayern": "bayern munich",
    "bvb": "borussia dortmund",
    "dortmund": "borussia dortmund",
    "leverkusen": "bayer leverkusen",
    "psg": "paris saint-germain",
    "paris": "paris saint-germain",
    "juve": "juventus",
    "bianconeri": "juventus",
    "milan": "ac milan",
    "rossoneri": "ac milan",
    "inter": "inter milan",
    "nerazzurri": "inter milan",
    "atleti": "atletico madrid",
    "colchoneros": "atletico madrid",
    "avfc": "aston villa",
    "villa": "aston villa",
    "nufc": "newcastle",
    "toon": "newcastle",
    "slb": "benfica",
    "sporting": "sporting cp",
    "fcp": "porto",
    "beastlybank": "beastly",
    "beastly fc": "beastly",
}


def get_club_theme(
    team_name: str,
    role_color: Optional[str] = None,
    custom_branding: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Intelligently resolve the club brand identity.
    Checks:
    1. Custom branding from database (if provided).
    2. Preset registry by exact or alias match.
    3. Custom dynamic theme based on Discord role color, generating harmonized kits & slogans.
    """
    clean_team = team_name.strip()
    key = clean_team.lower()

    # 1. Custom Branding from database
    if custom_branding:
        pri = custom_branding.get("kit_primary")
        if pri:
            sec = custom_branding.get("kit_secondary") or "#FFFFFF"
            return {
                "display_name": clean_team.upper(),
                "primary": pri,
                "secondary": sec,
                "dark": "#0F172A",
                "gk_primary": "#1E293B" if pri.lower() not in ["#1e293b", "#18181b"] else "#F59E0B",
                "gk_secondary": "#FFFFFF",
                "accent": pri,
                "slogan_1": custom_branding.get("slogan_1") or "PASSION. POWER. PRIDE.",
                "slogan_2": custom_branding.get("slogan_2") or "VICTORY IS OUR DESTINY.",
                "chant": custom_branding.get("chant") or f"THE PRIDE OF {clean_team.upper()}.",
                "mascot": "crest",
                "logo_url": custom_branding.get("logo_url"),
            }

    # 2. Check Aliases & Presets
    matched_key = CLUB_ALIASES.get(key)
    if not matched_key:
        for alias, target in CLUB_ALIASES.items():
            if alias in key:
                matched_key = target
                break

    if not matched_key:
        for preset_key in CLUB_PRESETS:
            if preset_key in key or key in preset_key:
                matched_key = preset_key
                break

    if matched_key and matched_key in CLUB_PRESETS:
        theme = dict(CLUB_PRESETS[matched_key])
        theme["display_name"] = clean_team.upper()
        return theme

    # 3. Dynamic Theme for Custom Server Clubs
    primary_color = role_color or "#0F766E"
    if not primary_color.startswith("#"):
        primary_color = f"#{primary_color}"
    if len(primary_color) not in [4, 7]:
        primary_color = "#0F766E"

    return {
        "display_name": clean_team.upper(),
        "primary": primary_color,
        "secondary": "#FFFFFF",
        "dark": "#0F172A",
        "gk_primary": "#1E293B",
        "gk_secondary": "#FFFFFF",
        "accent": primary_color,
        "slogan_1": "PASSION. POWER. PRIDE.",
        "slogan_2": "VICTORY IS OUR DESTINY.",
        "chant": f"THE PRIDE OF {clean_team.upper()}.",
        "mascot": "crest",
    }


def draw_mascot(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    mascot_type: str,
    color: str,
    size: float = 24.0,
) -> None:
    """Draw an iconic vector mascot / emblem for the club."""
    s = size / 24.0
    if mascot_type == "devil":
        draw.line([(cx, cy - 8 * s), (cx, cy + 14 * s)], fill=color, width=max(1, int(2.5 * s)))
        draw.line([(cx - 9 * s, cy - 2 * s), (cx + 9 * s, cy - 2 * s)], fill=color, width=max(1, int(2.5 * s)))
        draw.line([(cx - 9 * s, cy - 2 * s), (cx - 9 * s, cy - 10 * s)], fill=color, width=max(1, int(2.5 * s)))
        draw.polygon([(cx - 11 * s, cy - 8 * s), (cx - 9 * s, cy - 14 * s), (cx - 7 * s, cy - 8 * s)], fill=color)
        draw.line([(cx + 9 * s, cy - 2 * s), (cx + 9 * s, cy - 10 * s)], fill=color, width=max(1, int(2.5 * s)))
        draw.polygon([(cx + 7 * s, cy - 8 * s), (cx + 9 * s, cy - 14 * s), (cx + 11 * s, cy - 8 * s)], fill=color)
        draw.polygon([(cx - 3 * s, cy - 6 * s), (cx, cy - 14 * s), (cx + 3 * s, cy - 6 * s)], fill=color)
    elif mascot_type == "crown":
        pts = [
            (cx - 11 * s, cy + 7 * s), (cx + 11 * s, cy + 7 * s),
            (cx + 10 * s, cy - 5 * s), (cx + 4 * s, cy), (cx, cy - 9 * s),
            (cx - 4 * s, cy), (cx - 10 * s, cy - 5 * s)
        ]
        draw.polygon(pts, fill=color)
        draw.line([(cx - 11 * s, cy + 9 * s), (cx + 11 * s, cy + 9 * s)], fill=color, width=max(1, int(2.5 * s)))
    elif mascot_type == "cannon":
        draw.rounded_rectangle([cx - 11 * s, cy - 5 * s, cx + 9 * s, cy], radius=2, fill=color)
        draw.ellipse([cx - 5 * s, cy - 2 * s, cx + 7 * s, cy + 9 * s], outline=color, width=max(1, int(2.5 * s)))
    elif mascot_type == "lion":
        pts = [
            (cx - 5 * s, cy + 9 * s), (cx + 7 * s, cy + 9 * s),
            (cx + 6 * s, cy + 2 * s), (cx + 9 * s, cy - 2 * s),
            (cx + 5 * s, cy - 8 * s), (cx, cy - 10 * s),
            (cx - 5 * s, cy - 5 * s), (cx - 3 * s, cy + 2 * s)
        ]
        draw.polygon(pts, fill=color)
    elif mascot_type == "bird":
        pts = [
            (cx, cy - 11 * s), (cx + 8 * s, cy - 3 * s), (cx + 5 * s, cy + 4 * s),
            (cx + 2 * s, cy + 9 * s), (cx - 2 * s, cy + 9 * s),
            (cx - 5 * s, cy + 4 * s), (cx - 8 * s, cy - 3 * s)
        ]
        draw.polygon(pts, fill=color)
    elif mascot_type == "ship":
        draw.polygon([(cx - 10 * s, cy), (cx + 10 * s, cy), (cx + 6 * s, cy + 6 * s), (cx - 6 * s, cy + 6 * s)], fill=color)
        draw.line([(cx, cy), (cx, cy - 9 * s)], fill=color, width=max(1, int(2 * s)))
        draw.polygon([(cx, cy - 8 * s), (cx + 7 * s, cy - 4 * s), (cx, cy)], fill=color)
    elif mascot_type == "star":
        pts = []
        for i in range(10):
            r = (12 * s) if i % 2 == 0 else (5 * s)
            angle = i * math.pi / 5 - math.pi / 2
            pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        draw.polygon(pts, fill=color)
    elif mascot_type == "dragon":
        draw.polygon([(cx - 7 * s, cy + 8 * s), (cx + 7 * s, cy + 8 * s), (cx + 9 * s, cy - 2 * s), (cx, cy - 10 * s), (cx - 9 * s, cy - 2 * s)], fill=color)
    else:
        shield = [
            (cx - 9 * s, cy - 10 * s), (cx + 9 * s, cy - 10 * s),
            (cx + 9 * s, cy), (cx, cy + 11 * s), (cx - 9 * s, cy)
        ]
        draw.polygon(shield, fill=color)
        draw.polygon([(cx - 6 * s, cy - 7 * s), (cx + 6 * s, cy - 7 * s), (cx + 6 * s, cy), (cx, cy + 8 * s), (cx - 6 * s, cy)], fill="#FFFFFF")
        draw.polygon([(cx - 3 * s, cy - 4 * s), (cx + 3 * s, cy - 4 * s), (cx + 3 * s, cy), (cx, cy + 5 * s), (cx - 3 * s, cy)], fill=color)


def draw_jersey_kit(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    primary_color: str,
    secondary_color: str,
    number: Optional[int] = None,
    scale: float = 1.0,
    is_gk: bool = False,
    border_col: Optional[str] = None,
) -> None:
    """Draw an authentic 2D vector football jersey with sleeves, collar, drop shadow, and squad number."""
    s = scale
    body_half_w = 23 * s
    sleeve_w = 34 * s
    sleeve_bottom_y = cy - 4 * s
    top_y = cy - 27 * s
    bottom_y = cy + 25 * s

    shirt_pts = [
        (cx - 12 * s, top_y + 3 * s),
        (cx - 23 * s, top_y + 5 * s),
        (cx - sleeve_w, top_y + 17 * s),
        (cx - sleeve_w + 3 * s, sleeve_bottom_y),
        (cx - body_half_w, sleeve_bottom_y - 5 * s),
        (cx - body_half_w, bottom_y),
        (cx + body_half_w, bottom_y),
        (cx + body_half_w, sleeve_bottom_y - 5 * s),
        (cx + sleeve_w - 3 * s, sleeve_bottom_y),
        (cx + sleeve_w, top_y + 17 * s),
        (cx + 23 * s, top_y + 5 * s),
        (cx + 12 * s, top_y + 3 * s),
    ]

    # Drop shadow
    shadow_pts = [(x + 1.5 * s, y + 2.5 * s) for (x, y) in shirt_pts]
    draw.polygon(shadow_pts, fill="#CBD5E1")

    # Main shirt body
    outline_col = border_col or ("#334155" if primary_color.lower() in ["#ffffff", "#fff"] else "#1E293B")
    draw.polygon(shirt_pts, fill=primary_color, outline=outline_col, width=1)

    # Sleeve cuff trims
    draw.line([(cx - sleeve_w, top_y + 17 * s), (cx - sleeve_w + 3 * s, sleeve_bottom_y)], fill=secondary_color, width=max(1, int(2.5 * s)))
    draw.line([(cx + sleeve_w, top_y + 17 * s), (cx + sleeve_w - 3 * s, sleeve_bottom_y)], fill=secondary_color, width=max(1, int(2.5 * s)))

    # Collar (crew or V-neck)
    collar_pts = [(cx - 12 * s, top_y + 3 * s), (cx, top_y + 10 * s), (cx + 12 * s, top_y + 3 * s)]
    draw.line(collar_pts, fill=secondary_color, width=max(1, int(2.5 * s)))

    # Squad number on the back
    if number is not None:
        font_num = get_font(int(21 * s), bold=True)
        draw.text((cx, cy + 2 * s), str(number), fill=secondary_color, font=font_num, anchor="mm")


def draw_perspective_pitch(
    draw: ImageDraw.ImageDraw,
    x_center: float,
    top_y: float,
    bottom_y: float,
    top_w: float,
    bottom_w: float,
    line_color: str = "#CBD5E1",
) -> None:
    """Render subtle 3D perspective pitch trapezoid with markings."""
    tl_x = x_center - top_w / 2
    tr_x = x_center + top_w / 2
    bl_x = x_center - bottom_w / 2
    br_x = x_center + bottom_w / 2

    # Outer trapezoid boundary
    draw.polygon([(tl_x, top_y), (tr_x, top_y), (br_x, bottom_y), (bl_x, bottom_y)], outline=line_color, width=2)

    def get_x(norm_x: float, y: float) -> float:
        t = (y - top_y) / (bottom_y - top_y)
        w = top_w + t * (bottom_w - top_w)
        return x_center + (norm_x - 0.5) * w

    # Halfway line
    mid_y = (top_y + bottom_y) / 2
    draw.line([(get_x(0, mid_y), mid_y), (get_x(1, mid_y), mid_y)], fill=line_color, width=2)

    # Center circle (perspective ellipse)
    c_w = (top_w + (bottom_w - top_w) * 0.5) * 0.32
    c_h = (bottom_y - top_y) * 0.16
    draw.ellipse([x_center - c_w / 2, mid_y - c_h / 2, x_center + c_w / 2, mid_y + c_h / 2], outline=line_color, width=2)
    draw.ellipse([x_center - 3, mid_y - 3, x_center + 3, mid_y + 3], fill=line_color)

    # Opponent penalty area (top)
    box_top_y = top_y
    box_bot_y = top_y + (bottom_y - top_y) * 0.16
    box_w_top = 0.54
    draw.line([(get_x(0.5 - box_w_top / 2, box_bot_y), box_bot_y), (get_x(0.5 + box_w_top / 2, box_bot_y), box_bot_y)], fill=line_color, width=2)
    draw.line([(get_x(0.5 - box_w_top / 2, box_top_y), box_top_y), (get_x(0.5 - box_w_top / 2, box_bot_y), box_bot_y)], fill=line_color, width=2)
    draw.line([(get_x(0.5 + box_w_top / 2, box_top_y), box_top_y), (get_x(0.5 + box_w_top / 2, box_bot_y), box_bot_y)], fill=line_color, width=2)

    # Home penalty area (bottom)
    h_box_bot_y = bottom_y
    h_box_top_y = bottom_y - (bottom_y - top_y) * 0.18
    h_box_w = 0.58
    draw.line([(get_x(0.5 - h_box_w / 2, h_box_top_y), h_box_top_y), (get_x(0.5 + h_box_w / 2, h_box_top_y), h_box_top_y)], fill=line_color, width=2)
    draw.line([(get_x(0.5 - h_box_w / 2, h_box_top_y), h_box_top_y), (get_x(0.5 - h_box_w / 2, h_box_bot_y), h_box_bot_y)], fill=line_color, width=2)
    draw.line([(get_x(0.5 + h_box_w / 2, h_box_top_y), h_box_top_y), (get_x(0.5 + h_box_w / 2, h_box_bot_y), h_box_bot_y)], fill=line_color, width=2)

    # Home 6-yard box
    six_top_y = bottom_y - (bottom_y - top_y) * 0.07
    six_w = 0.28
    draw.line([(get_x(0.5 - six_w / 2, six_top_y), six_top_y), (get_x(0.5 + six_w / 2, six_top_y), six_top_y)], fill=line_color, width=1)
    draw.line([(get_x(0.5 - six_w / 2, six_top_y), six_top_y), (get_x(0.5 - six_w / 2, h_box_bot_y), h_box_bot_y)], fill=line_color, width=1)
    draw.line([(get_x(0.5 + six_w / 2, six_top_y), six_top_y), (get_x(0.5 + six_w / 2, h_box_bot_y), h_box_bot_y)], fill=line_color, width=1)


def compute_formation_coords(formation_name: str) -> List[Tuple[str, float, float]]:
    """Return the exact 11 tactical coordinates for the given formation."""
    if formation_name in EXACT_FORMATION_COORDS:
        return EXACT_FORMATION_COORDS[formation_name]

    clean = str(formation_name).strip().lower().replace("-", "").replace(" ", "")
    for k, v in EXACT_FORMATION_COORDS.items():
        k_clean = k.lower().replace("-", "").replace(" ", "")
        if k.lower() == str(formation_name).lower() or k_clean == clean:
            return v

    if clean in ("4213", "4213attack", "4231attack"):
        return EXACT_FORMATION_COORDS["4-2-1-3"]

    return EXACT_FORMATION_COORDS[DEFAULT_FORMATION]


def assign_players_to_formation_slots(
    formation_slots: List[Tuple[str, float, float]],
    players: List[Dict[str, Any]],
) -> List[Optional[Dict[str, Any]]]:
    """
    Intelligently assign available squad players to tactical formation slots.
    Uses 5-stage priority matching:
    1. Exact position
    2. Alternate registered positions
    3. Close tactical role (LWB <-> LB, CDM <-> CM, CAM <-> CM, LM <-> LW, CF <-> ST)
    4. Category match (Goalkeeper in GK, Defender in Def, Midfielder in Mid, Attacker in Att)
    5. Fallback for unassigned players
    """
    assignments: List[Optional[Dict[str, Any]]] = [None] * len(formation_slots)
    used_ids = set()
    available = list(players)

    # Pass 1: Exact position match
    for idx, (slot_pos, _, _) in enumerate(formation_slots):
        for p in available:
            pid = p.get("id") or id(p)
            if pid in used_ids:
                continue
            if (p.get("position") or "").upper() == slot_pos.upper():
                assignments[idx] = p
                used_ids.add(pid)
                break

    # Pass 2: Alternate registered position match
    for idx, (slot_pos, _, _) in enumerate(formation_slots):
        if assignments[idx] is not None:
            continue
        for p in available:
            pid = p.get("id") or id(p)
            if pid in used_ids:
                continue
            alt_raw = p.get("alt_positions") or ""
            alts = [a.strip().upper() for a in alt_raw.replace("/", ",").split(",") if a.strip()]
            if slot_pos.upper() in alts:
                assignments[idx] = p
                used_ids.add(pid)
                break

    # Pass 3: Close tactical role match
    role_substitutes = {
        "GK": [],
        "CB": ["LB", "RB", "SW", "CDM"],
        "LB": ["LWB", "CB", "LM"],
        "RB": ["RWB", "CB", "RM"],
        "LWB": ["LB", "LM"],
        "RWB": ["RB", "RM"],
        "CDM": ["CM", "CB"],
        "CM": ["CAM", "CDM", "LM", "RM"],
        "CAM": ["CM", "CF", "SS", "LW", "RW"],
        "LM": ["LW", "CM", "LWB", "LB"],
        "RM": ["RW", "CM", "RWB", "RB"],
        "LW": ["LM", "RW", "ST", "CF"],
        "RW": ["RM", "LW", "ST", "CF"],
        "CF": ["ST", "CAM", "SS"],
        "ST": ["CF", "LW", "RW", "CAM"],
    }
    for idx, (slot_pos, _, _) in enumerate(formation_slots):
        if assignments[idx] is not None:
            continue
        subs = role_substitutes.get(slot_pos.upper(), [])
        for p in available:
            pid = p.get("id") or id(p)
            if pid in used_ids:
                continue
            pos = (p.get("position") or "").upper()
            if pos in subs:
                assignments[idx] = p
                used_ids.add(pid)
                break

    # Pass 4: Broad positional category match
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


# ==============================================================================
# MAIN EXPORTED FUNCTION: GENERATE ADAPTIVE LINEUP CARD
# ==============================================================================

def generate_lineup_image(
    team_name: str,
    manager_name: str,
    formation_name: str,
    starting_players: Optional[List[Dict[str, Any]]] = None,
    bench_players: Optional[List[Dict[str, Any]]] = None,
    role_color: Optional[str] = None,
    custom_branding: Optional[Dict[str, Any]] = None,
    manager_avatar_bytes: Optional[bytes] = None,
) -> io.BytesIO:
    """
    Generate an authentic, broadcast-quality matchday program Starting 11 & Bench graphic.
    Fully adaptive to the club mentioned with dynamic kits, GK kits, mascots, slogans, and chants.
    Returns in-memory PNG BytesIO buffer.
    """
    theme = get_club_theme(team_name, role_color=role_color, custom_branding=custom_branding)
    width, height = 1080, 1620

    # Clean off-white background matching classic matchday program cards
    bg_color = "#F7F7F8"
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    pad = 32
    border_col = theme["accent"]

    # 1. Outer Framing & Chamfered/Indented Double Border
    draw.rectangle([pad, pad, width - pad, height - pad], outline=border_col, width=3)
    draw.rectangle([pad + 6, pad + 6, width - pad - 6, height - pad - 6], outline="#E2E8F0", width=1)

    # 2. Header: Crest, Mascot, Club Name, STARTING XI, Formation Pill
    crest_cy = pad + 45
    draw_mascot(draw, width // 2, crest_cy, theme["mascot"], theme["primary"], size=36)

    # Flanking Mascots (Left & Right)
    mascot_y = pad + 110
    draw_mascot(draw, pad + 70, mascot_y, theme["mascot"], theme["primary"], size=52)
    draw_mascot(draw, width - pad - 70, mascot_y, theme["mascot"], theme["primary"], size=52)

    # Main Club Name (Bold Condensed Uppercase)
    clean_team = theme["display_name"]
    font_title_size = 46 if len(clean_team) <= 18 else (38 if len(clean_team) <= 24 else 28)
    font_title = get_font(font_title_size, bold=True)
    draw.text((width // 2, pad + 110), clean_team, fill="#0F172A", font=font_title, anchor="mm")

    # STARTING XI divider line
    sub_y = pad + 165
    font_sub = get_font(18, bold=True)
    draw.line([(width // 2 - 260, sub_y), (width // 2 - 80, sub_y)], fill=border_col, width=2)
    draw.text((width // 2, sub_y), "STARTING XI", fill=border_col, font=font_sub, anchor="mm")
    draw.line([(width // 2 + 80, sub_y), (width // 2 + 260, sub_y)], fill=border_col, width=2)

    # Formation Pill (in club color)
    pill_y = pad + 200
    pill_w = 260
    pill_h = 32
    draw.rounded_rectangle(
        [width // 2 - pill_w // 2, pill_y - pill_h // 2, width // 2 + pill_w // 2, pill_y + pill_h // 2],
        radius=6,
        fill=theme["primary"],
    )
    font_form = get_font(16, bold=True)
    draw.text((width // 2, pill_y), formation_name.upper(), fill=theme["secondary"], font=font_form, anchor="mm")

    # 3. 3D Perspective Pitch
    pitch_top_y = pad + 235
    pitch_bot_y = pad + 950
    pitch_top_w = 760
    pitch_bot_w = 980
    draw_perspective_pitch(draw, width // 2, pitch_top_y, pitch_bot_y, pitch_top_w, pitch_bot_w, line_color="#CBD5E1")

    def get_pitch_pos(norm_x: float, norm_y: float) -> Tuple[float, float]:
        """Project normalized tactical coordinates onto the perspective pitch trapezoid."""
        y = pitch_top_y + norm_y * (pitch_bot_y - pitch_top_y)
        t = (y - pitch_top_y) / (pitch_bot_y - pitch_top_y)
        w = pitch_top_w + t * (pitch_bot_w - pitch_top_w)
        x = (width // 2) + (norm_x - 0.5) * w
        return x, y

    # 4. Render Starting 11 on the Perspective Pitch
    formation_slots = compute_formation_coords(formation_name)
    slot_assignments = assign_players_to_formation_slots(formation_slots, starting_players or [])

    font_name = get_font(13, bold=True)
    font_rat = get_font(11, bold=True)
    font_vacant = get_font(12, bold=False)

    for slot_idx, (slot_pos, norm_x, norm_y) in enumerate(formation_slots):
        px, py = get_pitch_pos(norm_x, norm_y)
        is_gk = (slot_pos == "GK")
        player = slot_assignments[slot_idx]

        # Colors for kit
        kit_pri = theme["gk_primary"] if is_gk else theme["primary"]
        kit_sec = theme["gk_secondary"] if is_gk else theme["secondary"]
        kit_border = theme.get("border_kit")

        if player:
            name = (player.get("player_name") or f"Player {slot_idx + 1}").upper()
            number = player.get("number") or (slot_idx + 1)
            rating = player.get("rating")

            # Draw authentic football shirt
            draw_jersey_kit(
                draw=draw,
                cx=px,
                cy=py - 10,
                primary_color=kit_pri,
                secondary_color=kit_sec,
                number=number,
                scale=1.08,
                is_gk=is_gk,
                border_col=kit_border,
            )

            # Player Name (cleanly truncated if too long)
            disp_name = name if len(name) <= 14 else name[:12] + ".."
            draw.text((px, py + 26), disp_name, fill="#0F172A", font=font_name, anchor="mm")

            # Dark Rating Pill
            if rating:
                bx0, by0 = px - 16, py + 36
                bx1, by1 = px + 16, py + 52
                draw.rounded_rectangle([bx0, by0, bx1, by1], radius=3, fill="#0F172A")
                draw.text((px, py + 44), str(rating), fill="#FFFFFF", font=font_rat, anchor="mm")
        else:
            # Vacant slot with clean outline
            r = 18
            draw.ellipse([px - r, py - 10 - r, px + r, py - 10 + r], outline="#94A3B8", width=2)
            draw.text((px, py - 10), slot_pos, fill="#64748B", font=font_rat, anchor="mm")
            draw.text((px, py + 20), "[VACANT]", fill="#94A3B8", font=font_vacant, anchor="mm")

    # 5. Bench / Substitutes Section
    subs_y = pad + 1040
    draw.line([(pad + 50, subs_y), (width // 2 - 80, subs_y)], fill=border_col, width=2)
    draw.text((width // 2, subs_y), "BENCH / SUBS", fill=border_col, font=get_font(16, bold=True), anchor="mm")
    draw.line([(width // 2 + 80, subs_y), (width - pad - 50, subs_y)], fill=border_col, width=2)

    # Use provided bench players or build minimal clean placeholder
    subs_list = bench_players if bench_players else []
    if subs_list:
        row1 = subs_list[:5]
        row2 = subs_list[5:10]

        def render_bench_row(players: List[Dict[str, Any]], y_center: float, n_slots: int) -> None:
            slot_w = (width - 2 * pad - 80) / n_slots
            start_x = pad + 40 + slot_w / 2
            for s_idx, sp in enumerate(players):
                scx = start_x + s_idx * slot_w
                pos_code = (sp.get("position") or "SUB").upper()
                is_sub_gk = (pos_code == "GK")
                sub_pri = theme["gk_primary"] if is_sub_gk else theme["primary"]
                sub_sec = theme["gk_secondary"] if is_sub_gk else theme["secondary"]

                # Mini jersey
                mini_x = scx - 45
                mini_y = y_center
                draw_jersey_kit(draw, mini_x, mini_y, sub_pri, sub_sec, number=None, scale=0.62, is_gk=is_sub_gk)
                draw.text((mini_x, mini_y + 1), pos_code[:3], fill=sub_sec, font=get_font(9, bold=True), anchor="mm")

                # Sub Name
                s_name = (sp.get("player_name") or "Sub").upper()
                draw.text((scx - 14, mini_y - 7), s_name[:12], fill="#0F172A", font=get_font(11, bold=True), anchor="lm")

                # Sub Rating box
                s_rat = sp.get("rating")
                if s_rat:
                    draw.rounded_rectangle([scx - 14, mini_y + 3, scx + 14, mini_y + 17], radius=2, fill="#0F172A")
                    draw.text((scx, mini_y + 10), str(s_rat), fill="#FFFFFF", font=get_font(9, bold=True), anchor="mm")

        if row1:
            render_bench_row(row1, subs_y + 40, max(5, len(row1)))
        if row2:
            render_bench_row(row2, subs_y + 88, 5)

    # 6. Manager & Tactical Philosophy Card
    mgr_y0 = subs_y + 130
    mgr_y1 = mgr_y0 + 95
    mgr_x0 = pad + 40
    mgr_x1 = width - pad - 40

    # Outer container
    draw.rounded_rectangle([mgr_x0, mgr_y0, mgr_x1, mgr_y1], radius=8, outline="#E2E8F0", fill="#FFFFFF", width=2)

    # Manager photo box (avatar or executive silhouette)
    photo_w = 90
    photo_box = [mgr_x0 + 10, mgr_y0 + 8, mgr_x0 + 10 + photo_w, mgr_y1 - 8]
    draw.rounded_rectangle(photo_box, radius=6, fill="#F1F5F9", outline="#CBD5E1")

    pasted_avatar = False
    if manager_avatar_bytes:
        try:
            av_img = Image.open(io.BytesIO(manager_avatar_bytes)).convert("RGBA")
            av_img = av_img.resize((photo_w, mgr_y1 - mgr_y0 - 16), Image.Resampling.LANCZOS)
            # Create rounded mask
            mask = Image.new("L", av_img.size, 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([0, 0, av_img.size[0], av_img.size[1]], radius=6, fill=255)
            img.paste(av_img, (int(photo_box[0]), int(photo_box[1])), mask)
            pasted_avatar = True
        except Exception:
            pass

    if not pasted_avatar:
        s_cx = (photo_box[0] + photo_box[2]) // 2
        draw.ellipse([s_cx - 14, mgr_y0 + 16, s_cx + 14, mgr_y0 + 44], fill="#1E293B")
        draw.polygon([
            (photo_box[0] + 8, photo_box[3]),
            (s_cx - 16, mgr_y0 + 48),
            (s_cx + 16, mgr_y0 + 48),
            (photo_box[2] - 8, photo_box[3])
        ], fill="#1E293B")

    # Manager Details with collision-safe layout
    info_x = mgr_x0 + photo_w + 30
    draw.text((info_x, mgr_y0 + 26), "MANAGER", fill=border_col, font=get_font(12, bold=True), anchor="lm")
    clean_mgr = manager_name.strip().upper()
    font_mgr = get_font(24 if len(clean_mgr) <= 15 else 20, bold=True)
    draw.text((info_x, mgr_y0 + 55), clean_mgr, fill="#0F172A", font=font_mgr, anchor="lm")

    # Safe divider positioning based on actual text length
    name_w = draw.textlength(clean_mgr, font=font_mgr)
    div_x = max(info_x + int(name_w) + 30, info_x + 190)
    draw.line([(div_x, mgr_y0 + 15), (div_x, mgr_y1 - 15)], fill="#E2E8F0", width=2)

    # Clipboard icon & Slogans
    clip_x = div_x + 35
    clip_y = (mgr_y0 + mgr_y1) // 2
    draw.rounded_rectangle([clip_x - 14, clip_y - 20, clip_x + 14, clip_y + 20], radius=3, outline=border_col, width=2)
    draw.rectangle([clip_x - 6, clip_y - 23, clip_x + 6, clip_y - 19], fill=border_col)
    # Tactical board lines
    draw.ellipse([clip_x - 6, clip_y - 8, clip_x - 2, clip_y - 4], fill=border_col)
    draw.ellipse([clip_x + 2, clip_y + 4, clip_x + 6, clip_y + 8], fill=border_col)
    draw.line([(clip_x - 4, clip_y - 6), (clip_x + 4, clip_y + 6)], fill=border_col, width=1)

    slogan_x = clip_x + 30
    draw.text((slogan_x, mgr_y0 + 32), theme["slogan_1"], fill="#334155", font=get_font(14, bold=True), anchor="lm")
    draw.text((slogan_x, mgr_y0 + 60), theme["slogan_2"], fill=border_col, font=get_font(15, bold=True), anchor="lm")

    # 7. Bottom Footer: Club Chant flanked by mascots
    footer_y = height - pad - 20
    draw.text((width // 2, footer_y), theme["chant"], fill="#1E293B", font=get_font(14, bold=True), anchor="mm")
    draw_mascot(draw, width // 2 + 200, footer_y, theme["mascot"], theme["primary"], size=20)
    draw_mascot(draw, width // 2 - 200, footer_y, theme["mascot"], theme["primary"], size=20)

    # 8. Export to BytesIO PNG buffer
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
