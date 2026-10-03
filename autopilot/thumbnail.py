"""Shorts thumbnail: a vivid frame from the video + bold 2-4 word hook text (Pillow, free).

Designed for the feed: high contrast, big readable words in the upper third
(the bottom of a Short is covered by the title/UI), one accent colour.
"""
import os
import subprocess

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

W, H = 1080, 1920
ACCENTS = [(255, 212, 0), (0, 230, 255), (255, 90, 90), (120, 255, 120)]


def _font_path():
    try:
        p = subprocess.run(["fc-match", "-f", "%{file}", "DejaVu Sans:bold"], capture_output=True, text=True).stdout
        if p and os.path.exists(p):
            return p
    except Exception:  # noqa: BLE001
        pass
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",):
        if os.path.exists(p):
            return p
    return None


def _grab_frame(video, t, out_png):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(t, 0):.2f}", "-i", video,
                    "-frames:v", "1", out_png], check=True)
    return out_png


def _wrap(draw, words, font, max_w):
    lines, cur = [], []
    for w in words:
        test = " ".join(cur + [w])
        if cur and draw.textlength(test, font=font) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def make(video, t, text, out_jpg, badge="", accent_index=0):
    """Create a 1080x1920 JPEG under 2 MB. Returns the path."""
    png = out_jpg.replace(".jpg", "_frame.png")
    _grab_frame(video, t, png)
    img = Image.open(png).convert("RGB").resize((W, H))
    os.remove(png)
    img = ImageEnhance.Color(img).enhance(1.3)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    # dark gradient at the top so the text pops
    shade = Image.new("L", (1, H))
    for y in range(H):
        shade.putpixel((0, y), int(200 * max(0.0, 1 - y / (H * 0.55))))
    img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, shade.resize((W, H)))

    draw = ImageDraw.Draw(img)
    fp = _font_path()
    accent = ACCENTS[accent_index % len(ACCENTS)]
    words = (text or "").upper().split()[:6]
    y = 210
    if badge:
        bf = ImageFont.truetype(fp, 230) if fp else ImageFont.load_default()
        draw.text((W // 2, y), badge, font=bf, fill=accent, anchor="ma", stroke_width=12, stroke_fill=(0, 0, 0))
        y += 270
    if words:
        size = 150
        while size > 80:
            font = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
            lines = _wrap(draw, words, font, W - 120)
            if len(lines) <= 3:
                break
            size -= 10
        for i, line in enumerate(lines):
            color = accent if i == len(lines) - 1 else (255, 255, 255)  # last line in the accent colour
            draw.text((W // 2, y), " ".join(line), font=font, fill=color, anchor="ma",
                      stroke_width=max(6, size // 14), stroke_fill=(0, 0, 0))
            y += int(size * 1.12)
    q = 90
    while True:
        img.save(out_jpg, "JPEG", quality=q, optimize=True)
        if os.path.getsize(out_jpg) < 1_900_000 or q <= 50:
            return out_jpg
        q -= 10
