"""
Clean & Minimal Matchday Starting 11 Lineup Image Generator.
Renders high-resolution broadcast-quality pitch graphics using Pillow.
"""
from __future__ import annotations

import io
import os
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from config import SUPPORTED_FORMATIONS, DEFAULT_FORMATION


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


def compute_formation_coords(formation_name: str) -> List[Tuple[str, float, float]]:
    """
    Calculate normalized (x, y) pitch coordinates for all 11 player positions.
    (0.0, 0.0) is top-left, (1.0, 1.0) is bottom-right.
    GK is at the bottom goal, attacking forwards are at the top.
    """
    data = SUPPORTED_FORMATIONS.get(formation_name)
    if not data:
        data = SUPPORTED_FORMATIONS.get(DEFAULT_FORMATION, list(SUPPORTED_FORMATIONS.values())[0])

    d_count = data["def"]
    m_count = data["mid"]
    f_count = data["fwd"]
    positions = data["positions"]

    coords: List[Tuple[str, float, float]] = []

    # 0: Goalkeeper (Anchored in bottom goal area)
    coords.append((positions[0], 0.50, 0.90))

    # 1..1+d: Defenders
    defs = positions[1 : 1 + d_count]
    if d_count == 3:
        xs = [0.26, 0.50, 0.74]
        for p, x in zip(defs, xs):
            coords.append((p, x, 0.78))
    elif d_count == 4:
        xs = [0.15, 0.38, 0.62, 0.85]
        ys = [0.75, 0.78, 0.78, 0.75]
        for p, x, y in zip(defs, xs, ys):
            coords.append((p, x, y))
    elif d_count == 5:
        xs = [0.12, 0.31, 0.50, 0.69, 0.88]
        ys = [0.70, 0.78, 0.79, 0.78, 0.70]
        for p, x, y in zip(defs, xs, ys):
            coords.append((p, x, y))
    else:
        step = 1.0 / (d_count + 1)
        for idx, p in enumerate(defs, start=1):
            coords.append((p, idx * step, 0.78))

    # Midfielders: positions[1+d_count : 1+d_count+m_count]
    mids = positions[1 + d_count : 1 + d_count + m_count]
    cdms = [p for p in mids if p == "CDM"]
    cams = [p for p in mids if p == "CAM"]
    flats = [p for p in mids if p not in ("CDM", "CAM")]

    # Map CDMs (Defensive pivot line)
    cdm_coords: List[Tuple[str, float, float]] = []
    if len(cdms) == 1:
        cdm_coords = [(cdms[0], 0.50, 0.62)]
    elif len(cdms) == 2:
        cdm_coords = [(cdms[0], 0.37, 0.62), (cdms[1], 0.63, 0.62)]
    elif len(cdms) >= 3:
        step = 0.60 / (len(cdms) - 1) if len(cdms) > 1 else 0
        cdm_coords = [(p, 0.20 + idx * step, 0.62) for idx, p in enumerate(cdms)]

    # Map Central & Wide Midfielders (LM, CM, RM, LWB, RWB)
    flat_coords: List[Tuple[str, float, float]] = []
    n_flat = len(flats)
    if n_flat == 1:
        flat_coords = [(flats[0], 0.50, 0.48)]
    elif n_flat == 2:
        flat_coords = [(flats[0], 0.36, 0.48), (flats[1], 0.64, 0.48)]
    elif n_flat == 3:
        flat_coords = [(flats[0], 0.24, 0.48), (flats[1], 0.50, 0.48), (flats[2], 0.76, 0.48)]
    elif n_flat == 4:
        flat_coords = [(flats[0], 0.15, 0.48), (flats[1], 0.38, 0.48), (flats[2], 0.62, 0.48), (flats[3], 0.85, 0.48)]
    elif n_flat == 5:
        flat_coords = [(flats[0], 0.13, 0.48), (flats[1], 0.31, 0.48), (flats[2], 0.50, 0.48), (flats[3], 0.69, 0.48), (flats[4], 0.87, 0.48)]
    elif n_flat >= 6:
        step = 0.76 / (n_flat - 1) if n_flat > 1 else 0
        flat_coords = [(p, 0.12 + idx * step, 0.48) for idx, p in enumerate(flats)]

    # Map CAMs (Advanced playmakers)
    cam_coords: List[Tuple[str, float, float]] = []
    n_cam = len(cams)
    if n_cam == 1:
        cam_coords = [(cams[0], 0.50, 0.34)]
    elif n_cam == 2:
        cam_coords = [(cams[0], 0.34, 0.34), (cams[1], 0.66, 0.34)]
    elif n_cam >= 3:
        cam_coords = [(cams[0], 0.24, 0.34), (cams[1], 0.50, 0.34), (cams[2], 0.76, 0.34)]

    # Merge midfield coords preserving original order
    mid_pool = list(cdm_coords + flat_coords + cam_coords)
    for p in mids:
        found = False
        for idx, (cp, cx, cy) in enumerate(mid_pool):
            if cp == p:
                coords.append((cp, cx, cy))
                mid_pool.pop(idx)
                found = True
                break
        if not found:
            coords.append((p, 0.50, 0.48))

    # Forwards: positions[1+d_count+m_count : 11]
    fwds = positions[1 + d_count + m_count : 11]
    if len(fwds) == 1:
        coords.append((fwds[0], 0.50, 0.16))
    elif len(fwds) == 2:
        coords.append((fwds[0], 0.36, 0.16))
        coords.append((fwds[1], 0.64, 0.16))
    elif len(fwds) == 3:
        if fwds in (["LW", "ST", "RW"], ["LW", "CF", "RW"]):
            coords.append((fwds[0], 0.17, 0.22))
            coords.append((fwds[1], 0.50, 0.16))
            coords.append((fwds[2], 0.83, 0.22))
        elif fwds == ["CF", "CF", "ST"]:
            coords.append((fwds[0], 0.33, 0.25))
            coords.append((fwds[1], 0.67, 0.25))
            coords.append((fwds[2], 0.50, 0.16))
        else:
            coords.append((fwds[0], 0.24, 0.18))
            coords.append((fwds[1], 0.50, 0.16))
            coords.append((fwds[2], 0.76, 0.18))
    elif len(fwds) == 4:
        coords.append((fwds[0], 0.14, 0.22))
        coords.append((fwds[1], 0.38, 0.16))
        coords.append((fwds[2], 0.62, 0.16))
        coords.append((fwds[3], 0.86, 0.22))
    else:
        for idx, p in enumerate(fwds):
            step = 0.60 / (len(fwds) - 1) if len(fwds) > 1 else 0
            coords.append((p, 0.20 + idx * step, 0.16))

    return coords[:11]


def draw_pitch_markings(draw: ImageDraw.ImageDraw, px0: int, py0: int, px1: int, py1: int) -> None:
    """Render minimal, elegant football pitch geometry."""
    pitch_w = px1 - px0
    pitch_h = py1 - py0
    center_x = px0 + pitch_w // 2
    mid_y = py0 + pitch_h // 2

    # Outer boundary border
    line_color = "#386641"  # Subtle emerald pitch line
    draw.rectangle([px0 + 20, py0 + 20, px1 - 20, py1 - 20], outline=line_color, width=2)

    # Halfway line
    draw.line([(px0 + 20, mid_y), (px1 - 20, mid_y)], fill=line_color, width=2)

    # Center circle & spot
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

    # Bottom penalty spot
    draw.ellipse([center_x - 4, py1 - 20 - 120 - 4, center_x + 4, py1 - 20 - 120 + 4], fill=line_color)


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
    """Draw a clean, minimalist player jersey badge and name pill on the pitch."""
    if font_num is None:
        font_num = get_font(18, bold=True)
    if font_name is None:
        font_name = get_font(14, bold=True)
    if font_pos is None:
        font_pos = get_font(11, bold=True)

    r = 24
    if is_vacant:
        # Vacant / Unassigned slot
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#0a1510", outline="#334155", width=2)
        draw.text((cx, cy), position, fill="#64748B", font=font_pos, anchor="mm")

        pill_w, pill_h = 110, 28
        p_x0 = cx - pill_w // 2
        p_y0 = cy + r + 4
        p_x1 = cx + pill_w // 2
        p_y1 = p_y0 + pill_h
        draw.rounded_rectangle([p_x0, p_y0, p_x1, p_y1], radius=6, fill="#070d0a", outline="#1e293b", width=1)
        draw.text((cx, p_y0 + pill_h // 2), "[Vacant]", fill="#64748B", font=font_pos, anchor="mm")
    else:
        # Occupied player slot
        # 1. Jersey Circle with Beastly Gold accent
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#0f172a", outline="#F59E0B", width=2)
        num_str = str(number) if number is not None else "-"
        draw.text((cx, cy), num_str, fill="#FFFFFF", font=font_num, anchor="mm")

        # 2. Sleek Name & Info Pill
        pill_w, pill_h = 130, 36
        p_x0 = cx - pill_w // 2
        p_y0 = cy + r + 4
        p_x1 = cx + pill_w // 2
        p_y1 = p_y0 + pill_h

        draw.rounded_rectangle([p_x0, p_y0, p_x1, p_y1], radius=8, fill="#0B131E", outline="#334155", width=1)

        # Truncate clean display name if needed
        disp_name = name[:13] + ".." if len(name) > 15 else name
        draw.text((cx, p_y0 + 11), disp_name, fill="#F8FAFC", font=font_name, anchor="mm")

        sub_info = f"{position}" + (f" • {rating}" if rating else "")
        draw.text((cx, p_y0 + 26), sub_info, fill="#38BDF8", font=font_pos, anchor="mm")


def generate_lineup_image(
    team_name: str,
    manager_name: str,
    formation_name: str,
    starting_players: Optional[List[Dict[str, Any]]] = None,
) -> io.BytesIO:
    """
    Generate a clean and minimal Starting 11 Matchday Pitch graphic.
    Completely excludes the bench to focus exclusively on the pitch lineup.
    Returns in-memory PNG BytesIO buffer.
    """
    width, height = 1080, 1440
    img = Image.new("RGB", (width, height), color="#07130c")
    draw = ImageDraw.Draw(img)

    # Load typography
    font_sub = get_font(20, bold=False)
    font_num = get_font(18, bold=True)
    font_name = get_font(14, bold=True)
    font_pos = get_font(11, bold=True)

    # Dynamic team name sizing
    clean_team = team_name.strip().upper()
    team_font_size = 38 if len(clean_team) <= 22 else (30 if len(clean_team) <= 30 else 24)
    font_team = get_font(team_font_size, bold=True)

    # 1. Clean Header Banner
    draw.text((width // 2, 50), clean_team, fill="#F8FAFC", font=font_team, anchor="mm")
    sub_text = f"MANAGER: {manager_name.strip()}   •   FORMATION: {formation_name.strip()}"
    draw.text((width // 2, 98), sub_text, fill="#94A3B8", font=font_sub, anchor="mm")

    # Hairline divider
    draw.line([(50, 138), (width - 50, 138)], fill="#1E293B", width=2)

    # 2. Football Pitch Dimensions
    px0, py0, px1, py1 = 40, 155, width - 40, height - 35
    pitch_w = px1 - px0
    pitch_h = py1 - py0

    # Draw pitch background with subtle alternating lawn stripes
    draw.rectangle([px0, py0, px1, py1], fill="#0e2317", outline="#1b4332", width=3)
    n_stripes = 10
    stripe_h = pitch_h / n_stripes
    for i in range(n_stripes):
        if i % 2 == 1:
            sy0 = py0 + i * stripe_h
            sy1 = sy0 + stripe_h
            draw.rectangle([px0, sy0, px1, sy1], fill="#112c1d")

    # Draw pitch lines & penalty areas
    draw_pitch_markings(draw, px0, py0, px1, py1)

    # 3. Compute Coordinates for 11 Positions
    formation_slots = compute_formation_coords(formation_name)

    # Match starting players to formation slots
    available_players = list(starting_players or [])
    used_player_ids = set()

    # First pass: Match players by exact position
    slot_assignments: List[Optional[Dict[str, Any]]] = [None] * 11
    for slot_idx, (pos_tag, _, _) in enumerate(formation_slots):
        for p in available_players:
            p_id = p.get("id") or id(p)
            if p_id not in used_player_ids and (p.get("position") or "").upper() == pos_tag.upper():
                slot_assignments[slot_idx] = p
                used_player_ids.add(p_id)
                break

    # Second pass: Fill unfilled slots with remaining starting players
    for slot_idx in range(11):
        if slot_assignments[slot_idx] is None:
            for p in available_players:
                p_id = p.get("id") or id(p)
                if p_id not in used_player_ids:
                    slot_assignments[slot_idx] = p
                    used_player_ids.add(p_id)
                    break

    # 4. Render 11 Player Badges on the Pitch
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

    # 5. Export to in-memory BytesIO buffer
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
