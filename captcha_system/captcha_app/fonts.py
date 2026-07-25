"""中文字体自动加载"""
import os
from PIL import ImageFont

_CJK_FONT_CACHE = {}

def load_cjk_font(size=26):
    """自动查找并加载支持中文的字体，结果按字号缓存。"""
    if size in _CJK_FONT_CACHE:
        return _CJK_FONT_CACHE[size]

    candidates = [
        # Noto CJK（常见于 Debian/Ubuntu，TTC 需指定 index，SC 简体一般在若干子字体中）
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", [0, 1, 2, 3, 4]),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", [0, 1, 2, 3, 4]),
        ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", [0, 1, 2, 3, 4]),
        ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", [0, 1, 2, 3, 4]),
        # 文泉驿 / 思源 / Droid
        ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", [0]),
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", [0]),
        ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", [None]),
        ("/usr/share/fonts/truetype/arphic/uming.ttc", [0]),
        ("/usr/share/fonts/truetype/arphic/ukai.ttc", [0]),
        # 项目内置字体（若用户放入 fonts/ 目录）
        (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "NotoSansSC-Regular.otf"), [None]),
        (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "SourceHanSansSC-Regular.otf"), [None]),
        (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "wqy-microhei.ttc"), [0]),
    ]

    # 再扫一遍系统字体目录，抓名字含 CJK/NotoSansSC/WenQuanYi/DroidSansFallback 的文件
    scan_dirs = [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        os.path.expanduser("~/.fonts"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts"),
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
                # 路径或文件名含关键字
                path_low = full.lower()
                if any(k in path_low for k in keywords):
                    candidates.append((full, [0, 1, 2, None] if low.endswith((".ttc", ".otc")) else [None]))

    test_char = "中"
    for path, indexes in candidates:
        if not os.path.isfile(path):
            continue
        for idx in indexes:
            try:
                if idx is None:
                    font = ImageFont.truetype(path, size)
                else:
                    font = ImageFont.truetype(path, size, index=idx)
                # 验证能否画出汉字（有的子字体是日韩，仍可画；用 getmask 或 textbbox 测）
                bbox = font.getbbox(test_char) if hasattr(font, "getbbox") else None
                if bbox and (bbox[2] - bbox[0]) > 2:
                    _CJK_FONT_CACHE[size] = font
                    print(f"[font] 使用中文字体: {path} index={idx} size={size}")
                    return font
            except Exception:
                continue

    # 最后兜底：默认字体（无中文，调用方应避免纯汉字）
    print("[font] 警告: 未找到中文字体，汉字可能显示为方框。请安装 fonts-noto-cjk 或将字体放入 fonts/ 目录")
    font = ImageFont.load_default()
    _CJK_FONT_CACHE[size] = font
    return font


