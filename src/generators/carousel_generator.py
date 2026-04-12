"""
carousel_generator.py — Generates 10-slide LinkedIn carousel as PDF.
Pillow renders each slide at 1080x1080. Pygments for code syntax highlighting.
Exports: individual PNGs + merged PDF (LinkedIn Document format).
"""

import os
import io
import json
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
try:
    from pygments import highlight
    from pygments.lexers import PythonLexer, JavaLexer
    from pygments.formatters import ImageFormatter
    PYGMENTS_OK = True
except ImportError:
    PYGMENTS_OK = False

# ─── Brand tokens ─────────────────────────────────────────────────────────────
BRAND = {
    "bg_dark":    (10, 14, 28),      # deep navy
    "bg_slide":   (15, 20, 42),      # slide background
    "bg_code":    (13, 17, 35),      # code block bg
    "accent":     (99, 102, 241),    # indigo — primary accent
    "accent2":    (236, 72, 153),    # pink — secondary accent
    "text":       (248, 250, 252),   # near-white
    "text_muted": (148, 163, 184),   # slate-400
    "green":      (34, 197, 94),
    "yellow":     (250, 204, 21),
    "red":        (239, 68, 68),
    "easy":       (34, 197, 94),
    "medium":     (250, 204, 21),
    "hard":       (239, 68, 68),
}

W = H = 1080
MARGIN = 60
CODE_FONT_SIZE = 24
TITLE_FONT_SIZE = 54
BODY_FONT_SIZE = 36
SUB_FONT_SIZE = 28


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    paths = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/liberation/LiberationSans-{'Bold' if bold else 'Regular'}.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _load_mono(size: int) -> ImageFont.FreeTypeFont:
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _new_slide() -> tuple[Image.Image, ImageDraw.Draw]:
    img = Image.new("RGB", (W, H), BRAND["bg_slide"])
    draw = ImageDraw.Draw(img)
    # Left accent bar
    draw.rectangle([0, 0, 8, H], fill=BRAND["accent"])
    return img, draw


def _draw_slide_number(draw: ImageDraw.Draw, n: int, total: int):
    font = _load_font(22)
    draw.text((W - MARGIN, H - 40), f"{n}/{total}",
              font=font, fill=BRAND["text_muted"], anchor="rm")


def _draw_tag(draw: ImageDraw.Draw, text: str, x: int, y: int, color=None):
    color = color or BRAND["accent"]
    font = _load_font(22, bold=True)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.rectangle([x, y, x + tw + 20, y + 30], fill=color)
    draw.text((x + 10, y + 4), text, font=font, fill=BRAND["text"])


def slide_hook(question: dict, part: dict) -> Image.Image:
    """Slide 1: Hook — big claim + company badge."""
    img, draw = _new_slide()
    # Top tag row
    companies = [c.strip().upper() for c in (question.get("companies") or "").split(",")][:3]
    x = MARGIN + 16
    for c in companies:
        _draw_tag(draw, c, x, 50, BRAND["accent"])
        x += len(c) * 14 + 40

    diff = question.get("difficulty", "medium").upper()
    diff_color = {"EASY": BRAND["easy"], "MEDIUM": BRAND["yellow"], "HARD": BRAND["red"]}.get(diff, BRAND["yellow"])
    _draw_tag(draw, diff, x, 50, diff_color)

    # Main title
    title = part.get("part_title") or question.get("title", "")
    font_title = _load_font(TITLE_FONT_SIZE, bold=True)
    lines = textwrap.wrap(title, width=18)
    y = 160
    for line in lines[:3]:
        draw.text((MARGIN + 16, y), line, font=font_title, fill=BRAND["text"])
        y += TITLE_FONT_SIZE + 12

    # Part badge if series
    if part.get("total_parts", 1) > 1:
        part_txt = f"Part {part['part_number']} of {part['total_parts']}"
        draw.text((MARGIN + 16, y + 10), part_txt, font=_load_font(SUB_FONT_SIZE),
                  fill=BRAND["accent2"])
        y += SUB_FONT_SIZE + 20

    # Hook text
    hook_text = "Most candidates fail this. Here's what Google actually tests."
    font_body = _load_font(BODY_FONT_SIZE)
    hook_lines = textwrap.wrap(hook_text, width=28)
    y = max(y + 40, 450)
    for line in hook_lines:
        draw.text((MARGIN + 16, y), line, font=font_body, fill=BRAND["text_muted"])
        y += BODY_FONT_SIZE + 8

    # Bottom accent
    draw.rectangle([0, H - 8, W, H], fill=BRAND["accent2"])
    _draw_slide_number(draw, 1, 10)
    return img


def slide_problem(question: dict) -> Image.Image:
    """Slide 2: Problem statement."""
    img, draw = _new_slide()
    draw.text((MARGIN + 16, 50), "The Problem", font=_load_font(44, bold=True), fill=BRAND["accent"])
    draw.line([(MARGIN + 16, 110), (W - MARGIN, 110)], fill=BRAND["accent"], width=2)

    desc = question.get("description", "")
    font = _load_font(BODY_FONT_SIZE - 4)
    lines = textwrap.wrap(desc, width=32)
    y = 140
    for line in lines[:8]:
        draw.text((MARGIN + 16, y), line, font=font, fill=BRAND["text"])
        y += BODY_FONT_SIZE + 6

    # Constraints badge
    draw.text((MARGIN + 16, H - 140), "Constraints matter — always ask.",
              font=_load_font(SUB_FONT_SIZE), fill=BRAND["accent2"])

    _draw_slide_number(draw, 2, 10)
    return img


def slide_wrong_approach(question: dict) -> Image.Image:
    """Slide 3: What fails and why."""
    img, draw = _new_slide()
    draw.text((MARGIN + 16, 50), "What Fails", font=_load_font(44, bold=True), fill=BRAND["red"])
    draw.line([(MARGIN + 16, 110), (W - MARGIN, 110)], fill=BRAND["red"], width=2)

    draw.text((MARGIN + 16, 140), "Brute Force:", font=_load_font(32, bold=True), fill=BRAND["text_muted"])
    lines = textwrap.wrap("Nested loops or naive recursion — most candidates start here.", width=32)
    y = 185
    for line in lines:
        draw.text((MARGIN + 16, y), line, font=_load_font(BODY_FONT_SIZE - 4), fill=BRAND["text"])
        y += BODY_FONT_SIZE + 6

    # Big red X
    font_big = _load_font(120, bold=True)
    draw.text((W//2, H//2 + 60), "O(n²)", font=font_big, fill=BRAND["red"], anchor="mm")
    draw.text((W//2, H//2 + 180), "Time Limit Exceeded ✗", font=_load_font(32),
              fill=BRAND["red"], anchor="mm")

    _draw_slide_number(draw, 3, 10)
    return img


def slide_dry_run_step(question: dict, step_num: int, total_steps: int = 4) -> Image.Image:
    """Slides 4-7: Dry run steps."""
    img, draw = _new_slide()
    step_text = f"Step {step_num}/{total_steps}"
    draw.text((MARGIN + 16, 50), step_text, font=_load_font(36, bold=True), fill=BRAND["accent"])

    dry_run = question.get("dry_run", "")
    # Split dry run into steps
    parts_raw = dry_run.replace("→", "\n→").split("\n")
    parts_raw = [p.strip() for p in parts_raw if p.strip()]
    step_idx = min(step_num - 1, len(parts_raw) - 1)
    current_step = parts_raw[step_idx] if parts_raw else dry_run[:100]

    font_body = _load_font(BODY_FONT_SIZE)
    lines = textwrap.wrap(current_step, width=26)
    y = 120
    for line in lines:
        draw.text((MARGIN + 16, y), line, font=font_body, fill=BRAND["text"])
        y += BODY_FONT_SIZE + 10

    # Progress bar
    progress = step_num / total_steps
    bar_w = W - 2 * MARGIN
    draw.rectangle([MARGIN, H - 80, MARGIN + int(bar_w * progress), H - 60],
                   fill=BRAND["accent"])
    draw.rectangle([MARGIN + int(bar_w * progress), H - 80, MARGIN + bar_w, H - 60],
                   fill=BRAND["bg_dark"])

    _draw_slide_number(draw, 3 + step_num, 10)
    return img


def slide_code(question: dict) -> Image.Image:
    """Slide 8: Code (Python)."""
    img, draw = _new_slide()
    draw.text((MARGIN + 16, 50), "Python Solution", font=_load_font(40, bold=True), fill=BRAND["green"])

    code = question.get("python_code", "# No code available")
    font_mono = _load_mono(CODE_FONT_SIZE)
    lines = code.split("\n")[:18]
    draw.rectangle([MARGIN, 110, W - MARGIN, H - 100], fill=BRAND["bg_code"])
    y = 130
    for line in lines:
        draw.text((MARGIN + 20, y), line, font=font_mono, fill=BRAND["text"])
        y += CODE_FONT_SIZE + 6

    _draw_slide_number(draw, 8, 10)
    return img


def slide_complexity(question: dict) -> Image.Image:
    """Slide 9: Complexity comparison table."""
    img, draw = _new_slide()
    draw.text((MARGIN + 16, 50), "Complexity", font=_load_font(44, bold=True), fill=BRAND["accent"])
    draw.line([(MARGIN + 16, 110), (W - MARGIN, 110)], fill=BRAND["accent"], width=2)

    approach = question.get("approach", "")
    rows = [
        ("Brute Force", "O(n²)", "O(1)", BRAND["red"]),
        ("Optimal", "O(n)", "O(n)", BRAND["green"]),
    ]
    y = 160
    font_b = _load_font(36, bold=True)
    font_r = _load_font(32)
    for label, time_c, space_c, color in rows:
        draw.text((MARGIN + 16, y), label, font=font_b, fill=color)
        draw.text((MARGIN + 16, y + 44), f"Time: {time_c}  ·  Space: {space_c}",
                  font=font_r, fill=BRAND["text_muted"])
        y += 140

    # Pattern tag
    pattern = question.get("pattern", "").replace("_", " ").title()
    draw.text((MARGIN + 16, H - 180), f"Pattern: {pattern}",
              font=_load_font(32, bold=True), fill=BRAND["accent2"])

    _draw_slide_number(draw, 9, 10)
    return img


def slide_cta(question: dict) -> Image.Image:
    """Slide 10: CTA."""
    img, draw = _new_slide()

    draw.text((W // 2, 200), "Follow for daily", font=_load_font(44), fill=BRAND["text_muted"], anchor="mm")
    draw.text((W // 2, 270), "FAANG patterns.", font=_load_font(56, bold=True), fill=BRAND["text"], anchor="mm")

    draw.text((W // 2, 430), "Next question tomorrow →",
              font=_load_font(36), fill=BRAND["accent"], anchor="mm")

    companies = [c.strip().upper() for c in (question.get("companies") or "").split(",")][:5]
    x = MARGIN + 16
    y = 560
    for c in companies:
        _draw_tag(draw, c, x, y, BRAND["accent"])
        x += len(c) * 14 + 50

    draw.rectangle([0, H - 8, W, H], fill=BRAND["accent2"])
    _draw_slide_number(draw, 10, 10)
    return img


def generate_carousel(question: dict, part: dict, output_dir: str) -> dict:
    """Generate all 10 slides + PDF. Returns paths dict."""
    os.makedirs(output_dir, exist_ok=True)

    slides = [
        slide_hook(question, part),
        slide_problem(question),
        slide_wrong_approach(question),
        slide_dry_run_step(question, 1, 4),
        slide_dry_run_step(question, 2, 4),
        slide_dry_run_step(question, 3, 4),
        slide_dry_run_step(question, 4, 4),
        slide_code(question),
        slide_complexity(question),
        slide_cta(question),
    ]

    png_paths = []
    for i, slide in enumerate(slides, 1):
        path = os.path.join(output_dir, f"slide_{i:02d}.png")
        slide.save(path, "PNG")
        png_paths.append(path)

    # Merge to PDF for LinkedIn Document upload
    pdf_path = os.path.join(output_dir, "carousel.pdf")
    slides[0].save(pdf_path, "PDF", save_all=True, append_images=slides[1:])

    print(f"[carousel] {len(slides)} slides → {pdf_path}")
    return {"pdf": pdf_path, "slides": png_paths}


if __name__ == "__main__":
    q = {
        "slug": "two-sum", "title": "Two Sum", "category": "dsa",
        "pattern": "two_pointer", "difficulty": "easy",
        "companies": "google,amazon,meta",
        "description": "Given an array and target, return indices of two numbers that add up to target.",
        "dry_run": "nums=[2,7,11,15],target=9 → store 2→0 → check 9-7=2 found → return [0,1]",
        "approach": "Hash map. O(n) time O(n) space.",
        "python_code": "def twoSum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        if target-n in seen: return [seen[target-n], i]\n        seen[n] = i",
    }
    part = {"part_number": 1, "total_parts": 1, "part_title": "Two Sum"}
    paths = generate_carousel(q, part, "output/carousel")
    print(paths)
