"""验证码图片生成：滑动 / 点选 / 文字"""
import math
import os
import secrets

from PIL import Image, ImageDraw, ImageFilter

from . import fonts, utils


def random_puzzle_spec():
    """随机拼图缺口形状：四条边各自随机 平直 / 外凸 / 内凹、半径与位置。

    返回 [(r, direction, pos), ...]，顺序为 上 / 右 / 下 / 左。
      - r=0 表示该边平直；
      - direction=1 外凸 / -1 内凹；
      - pos 为凸起中心在边上的归一化位置（0.35~0.65）。
    半径最大 7，保证凸起不超出拼图块画布的内边距 pad=8。
    每次生成至少两条边带凸起，避免退化成纯方块（降低模板匹配可行性）。
    """
    edges = []
    for _ in range(4):
        if secrets.randbelow(4) == 0:  # 约 25% 概率平直
            edges.append((0, 1, 0.5))
            continue
        r = 4 + secrets.randbelow(4)  # 4~7px
        direction = -1 if secrets.randbelow(3) == 0 else 1  # 1/3 内凹，2/3 外凸
        pos = (35 + secrets.randbelow(31)) / 100.0  # 0.35~0.65
        edges.append((r, direction, pos))
    # 保证至少两条边带凸起
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
    """构造拼图缺口多边形路径。

    edges 为 random_puzzle_spec() 的输出（上 / 右 / 下 / 左四边）；为 None 时
    退回经典四边外凸形状（兼容旧调用）。
    注意：同一次验证码必须把同一个 edges 传给蒙版 / 阴影 / 缺口三处调用，
    保证三块形状严丝合缝。
    """
    if edges is None:
        edges = [(min(bump, 7), 1, 0.5)] * 4
    # 各边：起点、沿边前进方向单位向量 u、朝外的法线单位向量 n（屏幕坐标 y 向下）
    sides = [
        ((x, y), (1, 0), (0, -1)),                # 上边，外侧朝上
        ((x + size, y), (0, 1), (1, 0)),          # 右边，外侧朝右
        ((x + size, y + size), (-1, 0), (0, 1)),  # 下边，外侧朝下
        ((x, y + size), (0, -1), (-1, 0)),        # 左边，外侧朝左
    ]
    path = [(x, y)]
    for (r, direction, pos), (a, (ux, uy), (nx, ny)) in zip(edges, sides):
        end = (a[0] + ux * size, a[1] + uy * size)
        if r <= 0:
            path.append(end)
            continue
        cx, cy = a[0] + ux * pos * size, a[1] + uy * pos * size
        # 直线到圆弧起点，再画半圆（direction=1 朝外鼓出，-1 朝内凹进）
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
    for _ in range(12):
        c = utils.random_color(100, 220)
        x, y = secrets.randbelow(width), secrets.randbelow(height)
        r = 8 + secrets.randbelow(40)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=c)
    for _ in range(6):
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

    # 每次生成随机缺口形状；pad 固定 8（handler 对齐与前端块尺寸均按 pad=8），
    # 凸起半径最大 7，不会越界裁切。
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


def generate_click_captcha(width=320, height=180, total_chars=6, click_count=3):
    """点选验证码：图上随机撒字，要求用户按顺序点击其中若干个。
    返回 (img, targets)
    targets = [{"char": "天", "x": 120, "y": 80}, ...]  # 需按顺序点击的目标中心坐标
    """
    # 常用汉字 + 字母数字，避免形近混淆可再精简
    pool = list("天地人和风雨雷电山川木火金石日月星云龙虎鸟鱼花草春秋夏冬东南西北")
    pool += list("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    secrets.SystemRandom().shuffle(pool)
    chars = pool[:total_chars]
    targets_chars = chars[:click_count]  # 前 click_count 个作为要点选的（顺序）

    img = Image.new("RGB", (width, height), utils.random_color(200, 245))
    draw = ImageDraw.Draw(img)

    # 背景干扰
    for _ in range(18):
        c = utils.random_color(140, 220)
        x, y = secrets.randbelow(width), secrets.randbelow(height)
        r = 6 + secrets.randbelow(28)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=c)
    for _ in range(10):
        c = utils.random_color(100, 180)
        draw.line(
            [(secrets.randbelow(width), secrets.randbelow(height)),
             (secrets.randbelow(width), secrets.randbelow(height))],
            fill=c, width=1
        )
    for _ in range(80):
        draw.point((secrets.randbelow(width), secrets.randbelow(height)), fill=utils.random_color(60, 160))

    font = fonts.load_cjk_font(26)

    # 放置字符，互不重叠
    placed = []  # {char, x, y, w, h}
    margin = 28
    attempts = 0
    idx = 0
    while idx < total_chars and attempts < 200:
        attempts += 1
        ch = chars[idx]
        # 估算文字尺寸
        try:
            bbox = draw.textbbox((0, 0), ch, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = 24, 28
        x = margin + secrets.randbelow(max(1, width - margin * 2 - tw))
        y = margin + secrets.randbelow(max(1, height - margin * 2 - th))
        cx, cy = x + tw / 2, y + th / 2
        # 与已放置保持距离
        ok = True
        for p in placed:
            if abs(cx - p["x"]) < 42 and abs(cy - p["y"]) < 42:
                ok = False
                break
        if not ok:
            continue
        color = utils.random_color(10, 90)
        # 单字旋转绘制，增加 OCR / 模板攻击难度
        angle = secrets.randbelow(41) - 20  # -20~+20 度
        pad = 8
        glyph = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glyph)
        gd.text((pad, pad), ch, font=font, fill=color + (255,))
        glyph = glyph.rotate(angle, expand=True, resample=Image.BICUBIC)
        # 贴回主图
        px = int(cx - glyph.width / 2)
        py = int(cy - glyph.height / 2)
        img.paste(glyph, (px, py), glyph)
        draw = ImageDraw.Draw(img)  # paste 后重建 draw
        placed.append({"char": ch, "x": cx, "y": cy, "w": tw, "h": th})
        idx += 1

    # 若放置不足，降级补齐
    while len(placed) < click_count:
        ch = secrets.choice(pool)
        x = margin + secrets.randbelow(width - margin * 2)
        y = margin + secrets.randbelow(height - margin * 2)
        draw.text((x, y), ch, font=font, fill=utils.random_color(10, 90))
        placed.append({"char": ch, "x": x + 12, "y": y + 12, "w": 24, "h": 28})

    # 目标顺序：从 placed 里按 targets_chars 顺序找（同一字符可能重复时取第一次）
    targets = []
    used = set()
    for ch in targets_chars:
        for i, p in enumerate(placed):
            if p["char"] == ch and i not in used:
                targets.append({"char": ch, "x": round(p["x"], 1), "y": round(p["y"], 1)})
                used.add(i)
                break
    # 兜底
    if len(targets) < click_count:
        targets = [{"char": p["char"], "x": round(p["x"], 1), "y": round(p["y"], 1)} for p in placed[:click_count]]

    # 前景干扰线（压在文字上，增加机器识别难度）
    draw = ImageDraw.Draw(img)
    for _ in range(5):
        c = utils.random_color(80, 160)
        draw.line(
            [(secrets.randbelow(width), secrets.randbelow(height)),
             (secrets.randbelow(width), secrets.randbelow(height))],
            fill=c, width=1 + secrets.randbelow(2),
        )
    img = img.filter(ImageFilter.SMOOTH)
    return img, targets


def generate_text_captcha(length=4, width=160, height=56):
    """保留旧文字验证码接口兼容"""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(chars) for _ in range(length))
    img = Image.new("RGB", (width, height), utils.random_color(220, 250))
    draw = ImageDraw.Draw(img)
    for _ in range(6):
        c = utils.random_color(100, 180)
        draw.line(
            [(secrets.randbelow(width), secrets.randbelow(height)),
             (secrets.randbelow(width), secrets.randbelow(height))],
            fill=c, width=1 + secrets.randbelow(2)
        )
    for _ in range(40):
        draw.point((secrets.randbelow(width), secrets.randbelow(height)), fill=utils.random_color(80, 160))
    font = fonts.load_cjk_font(32)
    char_w = width // (length + 1)
    for i, ch in enumerate(code):
        x = 12 + i * char_w + secrets.randbelow(6) - 3
        y = 8 + secrets.randbelow(10) - 4
        draw.text((x, y), ch, font=font, fill=utils.random_color(20, 100))
    img = img.filter(ImageFilter.SMOOTH)
    return img, code
