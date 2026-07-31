"""中文字体自动加载"""
import os
from PIL import ImageFont

_CJK_FONT_CACHE = {}
_SCANNED_CANDIDATES = None


def _scan_font_candidates():
    global _SCANNED_CANDIDATES
    if _SCANNED_CANDIDATES is not None:
        return _SCANNED_CANDIDATES

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fonts_dir = os.path.join(base, "fonts")

    candidates = [
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", [0, 1, 2, 3, 4]),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", [0, 1, 2, 3, 4]),
        ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", [0, 1, 2, 3, 4]),
        ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", [0, 1, 2, 3, 4]),
        ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", [0]),
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", [0]),
        ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", [None]),
        ("/usr/share/fonts/truetype/arphic/uming.ttc", [0]),
        ("/usr/share/fonts/truetype/arphic/ukai.ttc", [0]),
        (os.path.join(fonts_dir, "NotoSansSC-Regular.otf"), [None]),
        (os.path.join(fonts_dir, "SourceHanSansSC-Regular.otf"), [None]),
        (os.path.join(fonts_dir, "wqy-microhei.ttc"), [0]),
    ]

    scan_dirs = [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        os.path.expanduser("~/.fonts"),
        fonts_dir,
    ]
    keywords = ("cjk", "noto sans sc", "notosanssc", "wqy", "wenquan", "droid sans fallback",
                "source han", "sourcehan", "simhei", "simsun", "microsoft yahei", "pingfang")
    for root in scan_dirs:
        if not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            for fn in files:
                low = fn.lower()
                if not low.endswith((".ttf", ".ttc", ".otf", ".otc")):
                    continue
                full = os.path.join(dirpath, fn)
                path_low = full.lower()
                if any(k in path_low for k in keywords):
                    candidates.append((full, [0, 1, 2, None] if low.endswith((".ttc", ".otc")) else [None]))

    _SCANNED_CANDIDATES = candidates
    return candidates


def load_cjk_font(size=26):
    if size in _CJK_FONT_CACHE:
        return _CJK_FONT_CACHE[size]

    candidates = _scan_font_candidates()
    test_char = "中"
    for path, indexes in candidates:
        if not os.path.isfile(path):
            continue
        for idx in indexes:
            try:
                font = ImageFont.truetype(path, size) if idx is None else ImageFont.truetype(path, size, index=idx)
                bbox = font.getbbox(test_char) if hasattr(font, "getbbox") else None
                if bbox and (bbox[2] - bbox[0]) > 2:
                    _CJK_FONT_CACHE[size] = font
                    print(f"[font] 使用中文字体: {path} index={idx} size={size}")
                    return font
            except Exception:
                continue

    print("[font] 警告: 未找到中文字体，汉字可能显示为方框。请安装 fonts-noto-cjk 或将字体放入 fonts/ 目录")
    font = ImageFont.load_default()
    _CJK_FONT_CACHE[size] = font
    return font


