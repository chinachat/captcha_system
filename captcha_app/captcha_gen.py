"""验证码图片生成：滑动 / 点选 / 文字"""
import math
import secrets

from PIL import Image, ImageDraw, ImageFilter

from . import fonts, utils


def random_puzzle_spec():
    edges = []
    for _ in range(4):
        if secrets.randbelow(4) == 0:
            edges.append((0, 1, 0.5))
            continue
        r = 4 + secrets.randbelow(4)
        direction = -1 if secrets.randbelow(3) == 0 else 1
        pos = (35 + secrets.randbelow(31)) / 100.0
        edges.append((r, direction, pos))
    flat_idx = [i for i, e in enumerate(edges) if e[0] == 0]
    while len(flat_idx) > 2:
        i = flat_idx.pop(secrets.randbelow(len(flat_idx)))
        edges[i] = (
            4 + secrets.randbelow(4),
            -1 if secrets.randbelow(3) == 0 else 1,
            (35 + secrets.randbelow(31)) / 100.0,
        )
    return edges


def draw_puzzle_path(draw, x, y, size, bump=8, edges=None):
    if edges is None:
        edges = [(min(bump, 7), 1, 0.5)] * 4
    sides = [
        ((x, y), (1, 0), (0, -1)),
        ((x + size, y), (0, 1), (1, 0)),
        ((x + size, y + size), (-1, 0), (0, 1)),
        ((x, y + size), (0, -1), (-1, 0)),
    ]
    path = [(x, y)]
    for (r, direction, pos), (a, (ux, uy), (nx, ny)) in zip(edges, sides):
        end = (a[0] + ux * size, a[1] + uy * size)
        if r <= 0:
            path.append(end)
            continue
        cx, cy = a[0] + ux * pos * size, a[1] + uy * pos * size
        path.append((cx - ux * r, cy - uy * r))
        for i in range(9):
            ang = math.pi - i * math.pi / 8
            px = cx + ux * r * math.cos(ang) + nx * direction * r * math.sin(ang)
            py = cy + uy * r * math.cos(ang) + ny * direction * r * math.sin(ang)
            path.append((px, py))
        path.append(end)
    path.append((x, y))
    return path


def generate_slider_captcha(width=320, height=160, puzzle_size=42):
    bg = Image.new("RGB", (width, height), utils.random_color(80, 180))
    draw = ImageDraw.Draw(bg)
    for _ in range(10):
        c = utils.random_color(100, 220)
        x, y = secrets.randbelow(width), secrets.randbelow(height)
        r = 8 + secrets.randbelow(40)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=c)
    for _ in range(4):
        c = utils.random_color(60, 160)
        x1, y1 = secrets.randbelow(width), secrets.randbelow(height)
        x2 = x1 + 30 + secrets.randbelow(80)
        y2 = y1 + 20 + secrets.randbelow(40)
        draw.rectangle([x1, y1, x2, y2], fill=c)
    noise = Image.effect_noise((width, height), 12).convert("L")
    bg = Image.blend(bg, Image.merge("RGB", [noise] * 3), 0.08)

    margin = 20
    puzzle_x = margin + 40 + secrets.randbelow(max(1, width - puzzle_size - margin - 80))
    puzzle_y = margin + secrets.randbelow(max(1, height - puzzle_size - margin * 2))
    pad = 8
    spec = random_puzzle_spec()

    piece = Image.new("RGBA", (puzzle_size + pad * 2, puzzle_size + pad * 2), (0, 0, 0, 0))
    mask = Image.new("L", (puzzle_size + pad * 2, puzzle_size + pad * 2), 0)
    mask_draw = ImageDraw.Draw(mask)
    path = draw_puzzle_path(mask_draw, pad, pad, puzzle_size, edges=spec)
    mask_draw.polygon(path, fill=255)

    region = bg.crop((puzzle_x - pad, puzzle_y - pad, puzzle_x + puzzle_size + pad, puzzle_y + puzzle_size + pad))
    piece.paste(region, (0, 0))
    piece.putalpha(mask)

    bg_draw = ImageDraw.Draw(bg)
    shadow_path = draw_puzzle_path(bg_draw, puzzle_x + 2, puzzle_y + 2, puzzle_size, edges=spec)
    bg_draw.polygon(shadow_path, fill=(30, 30, 30))
    hole_path = draw_puzzle_path(bg_draw, puzzle_x, puzzle_y, puzzle_size, edges=spec)
    overlay = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.polygon(hole_path, fill=(20, 20, 40, 160))
    bg = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")

    piece_draw = ImageDraw.Draw(piece)
    piece_draw.polygon(path, outline=(255, 255, 255, 200))
    return bg, piece, puzzle_x, puzzle_y


def _text_bbox(draw, ch, font):
    """返回 textbbox，异常时给保守默认值。"""
    try:
        return draw.textbbox((0, 0), ch, font=font)
    except Exception:
        return (0, 0, 24, 28)


def _render_char_glyph(ch, font, draw, fill, pad=8):
    """按 bbox 偏移精确渲染单个字符。

    以 textbbox 的 left/top 偏移修正锚点，确保任意字体的字形都完整落在
    画布内（不会被底部/顶部裁剪）；返回 (glyph, ink_cx, ink_cy)，
    其中 ink 中心用于目标坐标，保证点击判定与视觉一致。
    """
    left, top, right, bottom = _text_bbox(draw, ch, font)
    tw, th = max(1, right - left), max(1, bottom - top)
    glyph = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glyph)
    gd.text((pad - left, pad - top), ch, font=font, fill=fill)
    return glyph, left + tw / 2, top + th / 2


def generate_click_captcha(width=320, height=180, total_chars=5, click_count=3):
    pool = list("天地上中水火土金风雷龙云山海花草春秋日月星光")
    pool += list("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    secrets.SystemRandom().shuffle(pool)
    chars = pool[:total_chars]
    targets_chars = chars[:click_count]

    img = Image.new("RGB", (width, height), utils.random_color(200, 245))
    draw = ImageDraw.Draw(img)

    for _ in range(12):
        c = utils.random_color(140, 220)
        x, y = secrets.randbelow(width), secrets.randbelow(height)
        r = 6 + secrets.randbelow(28)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=c)
    for _ in range(6):
        c = utils.random_color(100, 180)
        draw.line(
            [(secrets.randbelow(width), secrets.randbelow(height)),
             (secrets.randbelow(width), secrets.randbelow(height))],
            fill=c, width=1
        )
    for _ in range(60):
        draw.point((secrets.randbelow(width), secrets.randbelow(height)), fill=utils.random_color(60, 160))

    font = fonts.load_cjk_font(26)
    placed = []
    margin = 28
    attempts = 0
    idx = 0
    while idx < total_chars and attempts < 200:
        attempts += 1
        ch = chars[idx]
        left, top, right, bottom = _text_bbox(draw, ch, font)
        tw, th = max(1, right - left), max(1, bottom - top)
        x = margin + secrets.randbelow(max(1, width - margin * 2 - tw))
        y = margin + secrets.randbelow(max(1, height - margin * 2 - th))
        cx, cy = x + left + tw / 2, y + top + th / 2
        ok = True
        for p in placed:
            if abs(cx - p["x"]) < 42 and abs(cy - p["y"]) < 42:
                ok = False
                break
        if not ok:
            continue
        color = utils.random_color(10, 90)
        angle = secrets.randbelow(41) - 20
        glyph, ink_cx, ink_cy = _render_char_glyph(ch, font, draw, color + (255,))
        glyph = glyph.rotate(angle, expand=True, resample=Image.BICUBIC)
        px = int(cx - glyph.width / 2)
        py = int(cy - glyph.height / 2)
        img.paste(glyph, (px, py), glyph)
        draw = ImageDraw.Draw(img)
        placed.append({"char": ch, "x": cx, "y": cy, "w": tw, "h": th,
                       "ink_x": ink_cx, "ink_y": ink_cy})
        idx += 1

    while len(placed) < click_count:
        ch = secrets.choice(pool)
        left, top, right, bottom = _text_bbox(draw, ch, font)
        tw, th = max(1, right - left), max(1, bottom - top)
        x = margin + secrets.randbelow(max(1, width - margin * 2 - tw))
        y = margin + secrets.randbelow(max(1, height - margin * 2 - th))
        draw.text((x - left, y - top), ch, font=font, fill=utils.random_color(10, 90))
        placed.append({"char": ch, "x": x + left + tw / 2, "y": y + top + th / 2,
                       "w": tw, "h": th, "ink_x": left + tw / 2, "ink_y": top + th / 2})

    targets = []
    used = set()
    for ch in targets_chars:
        for i, p in enumerate(placed):
            if p["char"] == ch and i not in used:
                targets.append({"char": ch, "x": round(p["x"], 1), "y": round(p["y"], 1)})
                used.add(i)
                break
    if len(targets) < click_count:
        targets = [{"char": p["char"], "x": round(p["x"], 1), "y": round(p["y"], 1)} for p in placed[:click_count]]

    draw = ImageDraw.Draw(img)
    for _ in range(4):
        c = utils.random_color(80, 160)
        draw.line(
            [(secrets.randbelow(width), secrets.randbelow(height)),
             (secrets.randbelow(width), secrets.randbelow(height))],
            fill=c, width=1 + secrets.randbelow(2),
        )
    img = img.filter(ImageFilter.SMOOTH)
    return img, targets


def generate_text_captcha(length=4, width=160, height=56):
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(chars) for _ in range(length))
    img = Image.new("RGB", (width, height), utils.random_color(220, 250))
    draw = ImageDraw.Draw(img)
    for _ in range(4):
        c = utils.random_color(100, 180)
        draw.line(
            [(secrets.randbelow(width), secrets.randbelow(height)),
             (secrets.randbelow(width), secrets.randbelow(height))],
            fill=c, width=1 + secrets.randbelow(2)
        )
    for _ in range(30):
        draw.point((secrets.randbelow(width), secrets.randbelow(height)), fill=utils.random_color(80, 160))
    font = fonts.load_cjk_font(32)
    char_w = width // (length + 1)
    for i, ch in enumerate(code):
        left, top, right, bottom = _text_bbox(draw, ch, font)
        tw, th = max(1, right - left), max(1, bottom - top)
        x = 12 + i * char_w + secrets.randbelow(6) - 3
        y = max(0, (height - th) // 2) + secrets.randbelow(10) - 4
        draw.text((x - left, y - top), ch, font=font, fill=utils.random_color(20, 100))
    img = img.filter(ImageFilter.SMOOTH)
    return img, code
