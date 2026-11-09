# 生成界面美术资源（构建期跑一次，产物进 app\data\art\）
import os
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "app", "data", "art")
os.makedirs(OUT, exist_ok=True)

SRC = r"D:\Mental Omega\Resources\loadingscreen.png"

# 阵营代表色（取自官网阵营徽章）
THEME_ACCENT = {
    "def": (186, 130, 245),      # 默认：紫（与金色文字区分开）
    "allied": (127, 182, 255),   # 同盟国联军：蓝
    "soviet": (255, 138, 106),   # 苏维埃联盟：赤红
    "epsilon": (201, 155, 255),  # 厄普西隆军：紫
    "foehn": (121, 232, 221),    # 焚风反抗军：青
    "neutral": (206, 206, 214),  # 中立&其他：灰
}


def make_bg():
    im = Image.open(SRC).convert("RGB")
    w, h = 1600, 1000
    sc = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * sc + 1), int(im.height * sc + 1)), Image.LANCZOS)
    left = (im.width - w) // 2
    top = int((im.height - h) * 0.42)
    im = im.crop((left, top, left + w, top + h))
    im = im.filter(ImageFilter.GaussianBlur(1.4))
    im = ImageEnhance.Brightness(im).enhance(0.58)
    im = ImageEnhance.Color(im).enhance(1.15)
    tint = Image.new("RGB", im.size, (58, 26, 78))
    im = Image.blend(im, tint, 0.18)
    v = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(v)
    d.ellipse((-w * 0.35, -h * 0.35, w * 1.35, h * 1.35), fill=255)
    v = v.filter(ImageFilter.GaussianBlur(180))
    black = Image.new("RGB", (w, h), (0, 0, 0))
    im = Image.composite(im, black, v.point(lambda p: 155 + int(p * 0.39)))
    im.save(os.path.join(OUT, "bg.png"), optimize=True)


def make_banner():
    im = Image.open(SRC).convert("RGB")
    w, h = 1600, 96
    sc = w / im.width
    im = im.resize((w, int(im.height * sc) + 1), Image.LANCZOS)
    im = im.crop((0, 0, w, h))
    im = ImageEnhance.Brightness(im).enhance(0.72)
    im = ImageEnhance.Color(im).enhance(1.1)
    fade = Image.new("L", (1, h), 0)
    for y in range(h):
        t = max(0.0, (y - (h - 58)) / 58.0)
        fade.putpixel((0, y), int(255 * (t ** 1.4)))
    fade = fade.resize((w, h))
    dark = Image.new("RGB", (w, h), (7, 5, 11))
    im = Image.composite(dark, im, fade)
    im.save(os.path.join(OUT, "banner.png"), optimize=True)


def plate(w, h, state, accent=None):
    accent = accent or THEME_ACCENT["def"]
    im = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(im)
    if state == "idle":
        top, bot, border = (206, 206, 208), (146, 146, 150), (28, 24, 32)
    elif state == "hover":
        top, bot, border = (232, 232, 236), (176, 176, 182), (40, 34, 48)
    else:
        top = tuple(min(255, int(accent[i] * 0.62) + 26) for i in range(3))
        bot = tuple(int(accent[i] * 0.34) for i in range(3))
        border = (16, 12, 20)
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=c)
    hl = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dh = ImageDraw.Draw(hl)
    for i in range(-h, w, 26):
        dh.line([(i, h), (i + h, 0)], fill=(255, 255, 255, 16), width=5)
    im = Image.alpha_composite(im.convert("RGBA"), hl).convert("RGB")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w - 1, h - 1], outline=border)
    if state == "active":
        d.rectangle([1, 1, w - 2, h - 2], outline=tuple(min(255, int(c * 0.85)) for c in accent))
        d.rectangle([2, 2, w - 3, h - 3], outline=tuple(int(c * 0.30) for c in accent))
    else:
        d.line([(1, 1), (w - 2, 1)], fill=(255, 255, 255))
        d.line([(1, 1), (1, h - 2)], fill=(246, 246, 248))
        d.line([(1, h - 2), (w - 2, h - 2)], fill=(96, 94, 100))
        d.line([(w - 2, 2), (w - 2, h - 2)], fill=(112, 110, 116))
    for cx, cy in ((5, 5), (w - 6, 5), (5, h - 6), (w - 6, h - 6)):
        d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(70, 66, 76), outline=(24, 20, 30))
    return im


def make_buttons():
    sizes = {"btn": (96, 32), "btnf": (150, 32), "btnw": (136, 32), "btnbig": (200, 38)}
    for name, (w, h) in sizes.items():
        for state in ("idle", "hover"):
            plate(w, h, state).save(os.path.join(OUT, "%s_%s.png" % (name, state)), optimize=True)
    # 选中态：每个阵营一套（配色跟随阵营）
    for key, acc in THEME_ACCENT.items():
        plate(96, 32, "active", acc).save(os.path.join(OUT, "btn_active_%s.png" % key), optimize=True)
        plate(150, 32, "active", acc).save(os.path.join(OUT, "btnf_active_%s.png" % key), optimize=True)
    # 兼容旧文件名
    plate(96, 32, "active", THEME_ACCENT["def"]).save(os.path.join(OUT, "btn_active.png"), optimize=True)
    plate(150, 32, "active", THEME_ACCENT["def"]).save(os.path.join(OUT, "btnf_active.png"), optimize=True)


if __name__ == "__main__":
    make_bg()
    make_banner()
    make_buttons()
    for f in sorted(os.listdir(OUT)):
        print(f, os.path.getsize(os.path.join(OUT, f)))
