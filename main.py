# =============================================================================
# main.py  —  ESL Teacher Guide Auto-Annotation Pipeline (Final with Page Validation)
#
# Usage:
#   python main.py                    # process all PDFs in INPUT_FOLDER
#   python main.py path/to/file.pdf   # process a single PDF
#
# Requirements: pip install pymupdf openai
# =============================================================================

import sys
import json
import re
import base64
import threading
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz          # PyMuPDF
from openai import OpenAI

from api_config import (
    API_KEY, BASE_URL, MODEL, MAX_TOKENS,
    INPUT_FOLDER, OUTPUT_FOLDER, SYSTEM_PROMPT,
    EXPECTED_SLIDE_KEYS, MAX_WORKERS,
)

# =============================================================================
# Color constants  (RGB 0.0–1.0 for PyMuPDF)
# =============================================================================

def _hex(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))

RED        = _hex("CC1500")   # box borders, header backgrounds
YELLOW     = _hex("FDFDD3")   # box content background
BLUE       = _hex("1C60CD")   # time bar background
WHITE      = (1.0, 1.0, 1.0)
BLACK      = (0.0, 0.0, 0.0)
SAY_RED    = _hex("C80F12")   # Say First quote text
NOTE_PURPLE= _hex("72329D")   # Note text

# =============================================================================
# Progress helpers
# =============================================================================

_print_lock = threading.Lock()

def _log(prefix: str, msg: str):
    with _print_lock:
        print(f"  [{prefix}] {msg}", flush=True)

class Spinner:
    """Prints a start line, then a done line on exit. No intermediate output."""
    def __init__(self, prefix: str, label: str):
        self._prefix = prefix
        self._label = label

    def __enter__(self):
        _log(self._prefix, f"  {self._label}...")
        return self

    def __exit__(self, *_):
        _log(self._prefix, f"✓ {self._label}")


# =============================================================================
# Font loading
# =============================================================================

_ARIAL_PATH    = Path("C:/Windows/Fonts/arial.ttf")
_ARIALBD_PATH  = Path("C:/Windows/Fonts/arialbd.ttf")
_EMOJI_PATH    = Path("C:/Windows/Fonts/seguiemj.ttf")  # Segoe UI Emoji

def _load_fonts():
    """Load Arial from Windows Fonts. Falls back to built-in Helvetica."""
    if _ARIAL_PATH.exists() and _ARIALBD_PATH.exists():
        f_reg  = fitz.Font(fontfile=str(_ARIAL_PATH))
        f_bold = fitz.Font(fontfile=str(_ARIALBD_PATH))
        print("[font] Using Arial from Windows Fonts.")
    else:
        f_reg  = fitz.Font("helv")
        f_bold = fitz.Font("hebo")
        print("[font] Arial not found — using built-in Helvetica as fallback.")
    f_emoji = fitz.Font(fontfile=str(_EMOJI_PATH)) if _EMOJI_PATH.exists() else f_bold
    return f_reg, f_bold, f_emoji

FONT_REG, FONT_BOLD, FONT_EMOJI = _load_fonts()

# =============================================================================
# Data model (includes page_number)
# =============================================================================

@dataclass
class AnswerKey:
    items: list[str]

@dataclass
class SlideData:
    page_number:   int   # 1-based PDF page number
    slide_title:   str
    time_this:     float
    time_total:    float
    critical_check: str
    say_first:     str
    teaching_steps: list[str]
    challenge:     Optional[str] = None
    note:          Optional[str] = None
    answer_key:    Optional[AnswerKey] = None

# =============================================================================
# Step 1: PDF → PNG image bytes (one per page)
# =============================================================================

def pdf_to_images(doc: fitz.Document, dpi: int = 150) -> list[bytes]:
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        images.append(pix.tobytes("png"))
    return images

# =============================================================================
# Step 2: Call Claude API (with strict page separation instructions)
# =============================================================================

def call_claude_api(images: list[bytes], markdown_text: str = "") -> str:
    """
    Send all slide images and optional extracted text to the API.
    Text is sent first (as primary source), images as secondary reference.
    Returns the raw response text (expected to be JSON).
    """
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    # Build content blocks: first text (if provided), then images
    content = []

    if markdown_text.strip():
        # EXTREMELY STRICT INSTRUCTIONS to avoid answer key mixing
        content.append({
            "type": "text",
            "text": (
                "Here is the extracted text from the PDF (each page separated by '## Page N'):\n\n"
                f"{markdown_text}\n\n"
                "**CRITICAL RULES:**\n"
                "1. For EVERY slide, you MUST include a 'page_number' field that exactly matches the page number indicated by '## Page N' in the text above.\n"
                "2. The 'answer_key' items MUST belong exclusively to the page where they appear in the text. Do NOT mix answer items from different pages.\n"
                "3. If a page has multiple answer boxes, combine them into a single list in the order they appear.\n"
                "4. Double-check that the answer items on page X are not accidentally copied to page Y.\n"
                "\n"
                "Output valid JSON with a 'slides' array containing all required fields. No explanation, no markdown fences."
            )
        })
    else:
        # If no text, fall back to image-only instruction (still require page_number)
        content.append({
            "type": "text",
            "text": (
                "These are all the slides for one lesson. "
                "Process every slide and output the JSON only. "
                "Each slide object must include a 'page_number' field indicating the PDF page it belongs to (1-based). "
                "Ensure that answer keys are not mixed between pages. "
                "No explanation, no markdown fences."
            )
        })

    for img_bytes in images:
        b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

    max_attempts = 3
    wait_seconds = [10, 30, 60]
    last_error = None
    for attempt in range(max_attempts):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": content},
                ],
            )
            return response.choices[0].message.content
        except Exception as e:
            last_error = e
            if attempt < max_attempts - 1:
                wait = wait_seconds[attempt]
                with _print_lock:
                    print(f"  [retry] API error (attempt {attempt+1}/{max_attempts}): {e}. Retrying in {wait}s...", flush=True)
                time.sleep(wait)
    raise last_error

# =============================================================================
# Step 3: Parse JSON response → list[SlideData] (with step cleaning)
# =============================================================================

def _extract_json(raw: str) -> str:
    """Strip markdown code fences if present."""
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if m:
        return m.group(1)
    return raw

def _clean_step_text(step: str) -> str:
    """Remove leading numbering like '1. ' from a teaching step string."""
    return re.sub(r'^\d+\.\s*', '', step).strip()

def parse_response(raw: str) -> list[SlideData]:
    cleaned = _extract_json(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse error: {e}\nRaw response:\n{raw[:500]}")

    slides_raw = data.get("slides", [])
    if not slides_raw:
        raise ValueError("API response contains no 'slides' array.")

    slides = []
    for s in slides_raw:
        # Validate keys (now including page_number)
        missing = EXPECTED_SLIDE_KEYS - s.keys()
        if missing:
            with _print_lock:
                print(f"  [warn] Page {s.get('page_number','?')} missing keys: {missing}")

        ak_raw = s.get("answer_key")
        answer_key = AnswerKey(items=ak_raw["items"]) if ak_raw else None

        # Clean teaching steps to remove any AI-added numbering
        raw_steps = s.get("teaching_steps", [])
        cleaned_steps = [_clean_step_text(step) for step in raw_steps]

        slides.append(SlideData(
            page_number    = int(s.get("page_number", 0)),
            slide_title    = s.get("slide_title", ""),
            time_this      = float(s.get("time_this", 0)),
            time_total     = float(s.get("time_total", 0)),
            critical_check = s.get("critical_check", ""),
            say_first      = s.get("say_first", ""),
            teaching_steps = cleaned_steps,
            challenge      = s.get("challenge"),
            note           = s.get("note"),
            answer_key     = answer_key,
        ))

    slides.sort(key=lambda x: x.page_number)  # sort by page_number
    return slides

# =============================================================================
# Step 4: Map AI slide output → PDF page index (based on page_number)
# =============================================================================

def build_page_map(slides: list[SlideData], n_pages: int) -> dict[int, SlideData]:
    """
    Map each PDF page (0-based index) to a SlideData object using the page_number field.
    If a page has no slide assigned, use the nearest previous slide (or a blank placeholder).
    """
    mapping = {}
    for slide in slides:
        page_idx = slide.page_number - 1   # convert to 0-based
        if page_idx < 0 or page_idx >= n_pages:
            with _print_lock:
                print(f"  [warn] Page {slide.page_number} is out of range, ignoring.")
            continue
        if page_idx in mapping:
            with _print_lock:
                print(f"  [warn] Page {slide.page_number} already mapped, overwriting.")
        mapping[page_idx] = slide

    # Fill missing pages with the nearest previous slide (or create blank if none)
    last_valid = None
    for page_idx in range(n_pages):
        if page_idx in mapping:
            last_valid = mapping[page_idx]
        else:
            if last_valid is not None:
                mapping[page_idx] = last_valid
                with _print_lock:
                    print(f"  [info] Page {page_idx+1} has no slide, using slide from page {last_valid.page_number}.")
            else:
                mapping[page_idx] = SlideData(
                    page_number=page_idx+1,
                    slide_title="",
                    time_this=0,
                    time_total=0,
                    critical_check="",
                    say_first="",
                    teaching_steps=[],
                    challenge=None,
                    note=None,
                    answer_key=None
                )
                with _print_lock:
                    print(f"  [info] Page {page_idx+1} has no slide, created blank placeholder.")
    return mapping

# =============================================================================
# Step 4b: Optional post-processing to detect/correct answer key mixing
# =============================================================================

# =============================================================================
# Step 5: Drawing helpers
# =============================================================================

PAGE_W = 900.0
PAGE_H = 507.0

# Layout constants (absolute pt)
BOX_LEFT       = 432     # ~48% of 900pt  (matches template average)
BOX_RIGHT      = 880
BOX_TOP        = 26      # top of content area
HEADER_H       = 16      # header bar height
HEADER_LABEL_W = 103     # width of "TEACHER:" label bar
PADDING        = 7       # inner padding for content
LINE_H         = 13.5    # line height (pt)
FONT_SIZE      = 10.4
HEADER_FONT_SIZE = 14.0
TIME_FONT_SIZE = 11.4
INDENT         = 10      # indent for sub-items


def _draw_filled_rect(page, rect, fill, stroke=None, stroke_width=1.0, dashes=None):
    """Draw a rectangle with optional fill and optional dashed stroke."""
    shape = page.new_shape()
    shape.draw_rect(rect)
    kwargs = dict(fill=fill, color=stroke, width=stroke_width)
    if dashes:
        kwargs["dashes"] = dashes
    shape.finish(**kwargs)
    shape.commit()


def _draw_rounded_rect(page, rect, fill, stroke=None, stroke_width=1.0, radius=3):
    """Draw a rectangle with rounded corners."""
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(fill=fill, color=stroke, width=stroke_width, round_caps=True)
    shape.commit()


def _insert_text_line(page, x, y, text, font, fontsize, color):
    """Insert a single line of text using TextWriter."""
    tw = fitz.TextWriter(page.rect)
    tw.append((x, y), text, font=font, fontsize=fontsize)
    tw.write_text(page, color=color)


def _text_width(text, font, fontsize):
    """Estimate text width in pt."""
    return font.text_length(text, fontsize=fontsize)


def _wrap_text(text, font, fontsize, max_width):
    """Wrap text into lines that fit within max_width."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        if _text_width(test, font, fontsize) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines if lines else [""]


# =============================================================================
# TEACHER box
# =============================================================================

def _render_teacher_content(page, data: SlideData, bx0, by0, bx1, dry_run=False):
    """Render teacher box content.
    Returns (final_y, max_content_x) — used to size the box exactly.
    If dry_run=True, skips drawing but still tracks dimensions."""
    x0 = bx0 + PADDING
    max_w = bx1 - x0 - PADDING
    y = by0 + PADDING + FONT_SIZE
    max_x = bx0  # track rightmost content edge

    def text(px, py, t, font, size, color):
        nonlocal max_x
        w = _text_width(t, font, size)
        max_x = max(max_x, px + w)
        if not dry_run:
            _insert_text_line(page, px, py, t, font, size, color)

    # Critical Check
    cc_label_w = _text_width("Critical Check: ", FONT_BOLD, FONT_SIZE)
    cc_lines = _wrap_text(data.critical_check, FONT_BOLD, FONT_SIZE, max_w - cc_label_w)
    text(x0, y, "⚠ ", FONT_EMOJI, FONT_SIZE, BLACK)
    em_w = _text_width("⚠ ", FONT_EMOJI, FONT_SIZE)
    text(x0 + em_w, y, "Critical Check: ", FONT_BOLD, FONT_SIZE, BLACK)
    if cc_lines:
        text(x0 + em_w + cc_label_w, y, cc_lines[0], FONT_BOLD, FONT_SIZE, BLACK)
        for extra in cc_lines[1:]:
            y += LINE_H
            text(x0 + INDENT, y, extra, FONT_BOLD, FONT_SIZE, BLACK)
    y += LINE_H * 1.2

    # Say First
    sf_label = "Say First: "
    sf_label_w = _text_width(sf_label, FONT_REG, FONT_SIZE)
    quote_text = f'"{data.say_first}"'
    text(x0, y, "🗣 ", FONT_EMOJI, FONT_SIZE, BLACK)
    em_w = _text_width("🗣 ", FONT_EMOJI, FONT_SIZE)
    q_lines = _wrap_text(quote_text, FONT_BOLD, FONT_SIZE, max_w - em_w - sf_label_w)
    text(x0 + em_w, y, sf_label, FONT_REG, FONT_SIZE, BLACK)
    if q_lines:
        text(x0 + em_w + sf_label_w, y, q_lines[0], FONT_BOLD, FONT_SIZE, SAY_RED)
        for extra in q_lines[1:]:
            y += LINE_H
            text(x0 + INDENT, y, extra, FONT_BOLD, FONT_SIZE, SAY_RED)
    y += LINE_H * 1.2

    # Teaching Steps label
    text(x0 + INDENT, y, "📝 ", FONT_EMOJI, FONT_SIZE, BLACK)
    em_w = _text_width("📝 ", FONT_EMOJI, FONT_SIZE)
    text(x0 + INDENT + em_w, y, "Teaching Steps:", FONT_REG, FONT_SIZE, BLACK)
    y += LINE_H

    # Teaching Steps
    steps = data.teaching_steps
    for i, step in enumerate(steps, start=1):
        step_text = f"{i}. {step}"
        step_lines = _wrap_text(step_text, FONT_BOLD, FONT_SIZE, max_w - INDENT * 2)
        for j, line in enumerate(step_lines):
            text(x0 + INDENT * 2, y, line, FONT_BOLD, FONT_SIZE, BLACK)
            if i < len(steps) or j < len(step_lines) - 1:
                y += LINE_H

    # Challenge
    if data.challenge:
        y += LINE_H
        ch_label = "Challenge (Optional): "
        ch_label_w = _text_width(ch_label, FONT_REG, FONT_SIZE)
        text(x0 + INDENT, y, "📈 ", FONT_EMOJI, FONT_SIZE, BLACK)
        em_w = _text_width("📈 ", FONT_EMOJI, FONT_SIZE)
        # Available width: use full page width minus left offset for challenge
        ch_available_w = (PAGE_W - 10) - (x0 + INDENT + em_w + ch_label_w)
        ch_lines = _wrap_text(data.challenge, FONT_BOLD, FONT_SIZE, ch_available_w)
        text(x0 + INDENT + em_w, y, ch_label, FONT_REG, FONT_SIZE, BLACK)
        if ch_lines:
            text(x0 + INDENT + em_w + ch_label_w, y, ch_lines[0], FONT_BOLD, FONT_SIZE, BLACK)
            for extra in ch_lines[1:]:
                y += LINE_H
                text(x0 + INDENT + em_w + ch_label_w, y, extra, FONT_BOLD, FONT_SIZE, BLACK)

    # Note
    if data.note:
        y += LINE_H * 2
        note_segments = data.note.split("\n")
        all_note_lines = []
        for seg in note_segments:
            all_note_lines.extend(_wrap_text(seg, FONT_BOLD, FONT_SIZE, max_w))
        for i, line in enumerate(all_note_lines):
            text(x0, y, line, FONT_BOLD, FONT_SIZE, NOTE_PURPLE)
            if i < len(all_note_lines) - 1:
                y += LINE_H

    return y + 5, max_x + PADDING  # (final_y, right edge with padding)


def draw_teacher_box(page: fitz.Page, data: SlideData):
    """Draw the TEACHER annotation box on the right side of the page."""
    bx0 = float(BOX_LEFT)
    by0 = float(BOX_TOP)

    # Pass 1: measure max content width (no wrapping constraint)
    _, max_x = _render_teacher_content(None, data, bx0, by0, PAGE_W - 2, dry_run=True)
    bx1 = min(max_x, PAGE_W - 2)

    # Pass 2: measure exact height using the final bx1 (same max_w as actual render)
    final_y, _ = _render_teacher_content(None, data, bx0, by0, bx1, dry_run=True)
    by1 = max(final_y, by0 + 80)

    # Draw box
    hdr_rect = fitz.Rect(bx0, by0 - HEADER_H, bx0 + HEADER_LABEL_W, by0 + 1)
    _draw_filled_rect(page, hdr_rect, fill=RED)
    _draw_filled_rect(page, hdr_rect, fill=None, stroke=RED, stroke_width=1.0, dashes="[3 2] 0")

    content_rect = fitz.Rect(bx0, by0, bx1, by1)
    _draw_filled_rect(page, content_rect, fill=YELLOW)
    _draw_filled_rect(page, content_rect, fill=None, stroke=RED, stroke_width=1.0, dashes="[3 2] 0")

    _insert_text_line(page, bx0 + 4, by0 - 3, "TEACHER:", FONT_BOLD, HEADER_FONT_SIZE, WHITE)

    # Pass 3: actual render with same bx1
    _render_teacher_content(page, data, bx0, by0, bx1, dry_run=False)


# =============================================================================
# ANSWER KEY box
# =============================================================================

def draw_answer_key_box(page: fitz.Page, data: SlideData):
    """Draw the ANSWER KEY box at the bottom-left if answer_key is present."""
    if not data.answer_key or not data.answer_key.items:
        return

    items = data.answer_key.items
    LABEL_W  = 110
    BOX_X0   = 48.0
    BOX_Y_BASE = PAGE_H - 15

    # Compute time bar left edge to use as max width limit (compact format)
    def _time_tx0():
        def fmt(v): return str(int(v)) if v == int(v) else str(v)
        label = f"{fmt(data.time_this)} min | {fmt(data.time_total)}/25"
        text_w = _text_width(label, FONT_BOLD, TIME_FONT_SIZE)
        return PAGE_W - 2 - text_w - 12

    max_item_w_allowed = _time_tx0() - BOX_X0 - PADDING * 2

    # Wrap each item to fit within allowed width
    wrapped_lines = []
    for item in items:
        lines = _wrap_text(item, FONT_BOLD, FONT_SIZE, max_item_w_allowed)
        wrapped_lines.extend(lines if lines else [item])

    # Box width: fit the longest wrapped line (capped at allowed width)
    max_line_w = max(_text_width(l, FONT_BOLD, FONT_SIZE) for l in wrapped_lines)
    akx1 = BOX_X0 + max(LABEL_W, min(max_line_w, max_item_w_allowed) + PADDING * 2)

    content_h = len(wrapped_lines) * LINE_H + PADDING * 2
    total_h   = content_h + HEADER_H
    aky0 = BOX_Y_BASE - total_h
    aky1 = BOX_Y_BASE

    # Header bar
    hdr = fitz.Rect(BOX_X0, aky0, BOX_X0 + LABEL_W, aky0 + HEADER_H)
    _draw_filled_rect(page, hdr, fill=RED)
    _draw_filled_rect(page, hdr, fill=None, stroke=RED, stroke_width=1.0, dashes="[3 2] 0")

    # Content area
    content_rect = fitz.Rect(BOX_X0, aky0 + HEADER_H, akx1, aky1)
    _draw_filled_rect(page, content_rect, fill=YELLOW)
    _draw_filled_rect(page, content_rect, fill=None, stroke=RED, stroke_width=1.0, dashes="[3 2] 0")

    # Header text
    _insert_text_line(page, BOX_X0 + 4, aky0 + HEADER_H - 3, "ANSWER KEY:",
                      FONT_BOLD, HEADER_FONT_SIZE, WHITE)

    # Answer items (wrapped)
    y = aky0 + HEADER_H + PADDING + FONT_SIZE
    for line in wrapped_lines:
        _insert_text_line(page, BOX_X0 + PADDING, y, line, FONT_BOLD, FONT_SIZE, BLACK)
        y += LINE_H


# =============================================================================
# Time bar
# =============================================================================

def draw_time_bar(page: fitz.Page, data: SlideData):
    """Draw the blue time indicator at the bottom-right. Compact version without emoji."""
    def fmt(v): return str(int(v)) if v == int(v) else str(v)
    # Compact format: "3.5 min | 16.5/25"
    label = f"{fmt(data.time_this)} min | {fmt(data.time_total)}/25"

    text_w = _text_width(label, FONT_BOLD, TIME_FONT_SIZE)
    bar_h  = TIME_FONT_SIZE * 1.8  # Smaller height
    tx1    = PAGE_W - 2
    tx0    = tx1 - text_w - 12    # Less padding
    ty1    = PAGE_H - 4
    ty0    = ty1 - bar_h

    bar_rect = fitz.Rect(tx0, ty0, tx1, ty1)
    _draw_filled_rect(page, bar_rect, fill=BLUE)
    _draw_filled_rect(page, bar_rect, fill=None, stroke=WHITE, stroke_width=1.0, dashes="[3 2] 0")

    text_y = ty0 + (ty1 - ty0) / 2 + TIME_FONT_SIZE * 0.35
    _insert_text_line(page, tx0 + 6, text_y, label, FONT_BOLD, TIME_FONT_SIZE, WHITE)


# =============================================================================
# Adult Warning box  (page 1 only — fixed content) - larger font (14pt)
# =============================================================================

ADULT_WARNING_TEXT = (
    "This is an adult class.\n"
    "Please remove any child-themed\n"
    "headgear and maintain a\n"
    "professional, neutral appearance."
)

def draw_adult_warning(page: fitz.Page):
    """Draw the fixed red adult-class warning box (page 1 only) with larger bold text."""
    wx0, wy0, wx1, wy1 = 35.0, 25.0, 300.0, 140.0
    warn_rect = fitz.Rect(wx0, wy0, wx1, wy1)

    _draw_filled_rect(page, warn_rect, fill=RED)
    _draw_filled_rect(page, warn_rect, fill=None, stroke=RED,
                      stroke_width=1.0, dashes="[3 2] 0")

    # Warning triangle emoji
    _insert_text_line(page, (wx0 + wx1) / 2 - 10, wy0 + 20, "⚠",
                      FONT_EMOJI, 16.0, WHITE)

    # Warning text lines - font size increased to 14.0
    lines = [l for l in ADULT_WARNING_TEXT.split("\n") if l.strip()]
    avail_w = wx1 - wx0 - 10
    y = wy0 + 32
    line_height = 18  # increased to fit larger text
    for line in lines:
        line_w = _text_width(line, FONT_BOLD, 14.0)
        x = wx0 + (avail_w - line_w) / 2 + 5
        _insert_text_line(page, x, y, line, FONT_BOLD, 14.0, WHITE)
        y += line_height


# =============================================================================
# Main overlay function for a single page
# =============================================================================

def overlay_annotations(page: fitz.Page, data: SlideData, page_idx: int):
    """Overlay all annotation boxes onto a single PDF page."""
    draw_teacher_box(page, data)
    draw_answer_key_box(page, data)
    draw_time_bar(page, data)
    if page_idx == 0:
        draw_adult_warning(page)


# =============================================================================
# Full pipeline for a single PDF file
# =============================================================================

def process_pdf(pdf_path: Path, pdf_dir: Path, json_dir: Path, rel_parent: Path = Path(".")) -> dict:
    """Returns a result dict: {file, status, output, error}"""
    name = pdf_path.name
    _log(name, "Starting...")

    try:
        doc = fitz.open(str(pdf_path))
        n_pages = len(doc)
        _log(name, f"{n_pages} pages found")

        # Extract text
        markdown_pages = []
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text()
            markdown_pages.append(f"## Page {page_num}\n\n{text}\n\n---\n")
        full_markdown = "\n".join(markdown_pages)

        # Convert to images
        with Spinner(name, "Converting pages to images"):
            images = pdf_to_images(doc)

        # Call API
        with Spinner(name, f"Waiting for API ({len(images)} slides)"):
            raw_response = call_claude_api(images, markdown_text=full_markdown)

        debug_path = json_dir / (pdf_path.stem + "_api_response.json")
        debug_path.write_text(raw_response, encoding="utf-8")

        # Parse
        try:
            slides = parse_response(raw_response)
        except ValueError as e:
            _log(name, f"[ERROR] Failed to parse API response: {e}")
            doc.close()
            return {"file": str(pdf_path), "status": "failed", "output": None, "error": f"Parse error: {e}"}

        _log(name, f"AI generated {len(slides)} slides for {n_pages} pages")
        page_map = build_page_map(slides, n_pages)

        # Annotate
        _log(name, f"Annotating {n_pages} pages...")
        for page_idx, page in enumerate(doc):
            overlay_annotations(page, page_map[page_idx], page_idx)
        _log(name, f"✓ Annotating done")

        out_subdir = pdf_dir / rel_parent
        out_subdir.mkdir(parents=True, exist_ok=True)
        out_path = out_subdir / (pdf_path.stem + "-TG draft.pdf")
        doc.save(str(out_path), garbage=4, deflate=True)
        doc.close()
        _log(name, f"Saved → {out_path.name}")
        return {"file": str(pdf_path), "status": "success", "output": str(out_path), "error": None}

    except Exception as e:
        return {"file": str(pdf_path), "status": "failed", "output": None, "error": str(e)}


# =============================================================================
# Entry point
# =============================================================================

def main():
    import json as _json
    from datetime import datetime

    output_dir = Path(OUTPUT_FOLDER)
    pdf_dir  = output_dir / "pdf"
    json_dir = output_dir / "json"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)

    if len(sys.argv) > 1:
        # Single file mode
        targets = [(Path(sys.argv[1]), Path("."))]
    else:
        # Batch mode: process all PDFs in INPUT_FOLDER (recursive)
        input_dir = Path(INPUT_FOLDER)
        if not input_dir.exists():
            print(f"[ERROR] Input folder not found: {input_dir}")
            sys.exit(1)
        pdf_files = sorted(input_dir.rglob("*.pdf"))
        if not pdf_files:
            print(f"[INFO] No PDF files found in {input_dir}")
            sys.exit(0)
        targets = [(p, p.parent.relative_to(input_dir)) for p in pdf_files]

    print(f"Found {len(targets)} PDF(s) to process. (MAX_WORKERS={MAX_WORKERS})")

    results = []

    if MAX_WORKERS <= 1 or len(targets) == 1:
        for pdf_path, rel_parent in targets:
            result = process_pdf(pdf_path, pdf_dir, json_dir, rel_parent)
            results.append(result)
            if result["status"] == "failed":
                print(f"  [ERROR] Failed to process {pdf_path.name}: {result['error']}")
    else:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_path = {
                executor.submit(process_pdf, pdf_path, pdf_dir, json_dir, rel_parent): pdf_path
                for pdf_path, rel_parent in targets
            }
            for future in as_completed(future_to_path):
                pdf_path = future_to_path[future]
                try:
                    result = future.result()
                except Exception as e:
                    import traceback
                    result = {"file": str(pdf_path), "status": "failed", "output": None, "error": str(e)}
                    traceback.print_exc()
                results.append(result)
                if result["status"] == "failed":
                    print(f"  [ERROR] Failed to process {pdf_path.name}: {result['error']}")

    # Write JSONL report
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"run_report_{run_ts}.jsonl"
    with open(report_path, "w", encoding="utf-8") as f:
        for r in sorted(results, key=lambda x: x["file"]):
            f.write(_json.dumps(r, ensure_ascii=False) + "\n")

    success = sum(1 for r in results if r["status"] == "success")
    failed  = sum(1 for r in results if r["status"] == "failed")
    print(f"\nDone. {success} succeeded, {failed} failed.")
    print(f"Report → {report_path.name}")
    if failed:
        print("Failed files:")
        for r in results:
            if r["status"] == "failed":
                print(f"  - {Path(r['file']).name}: {r['error']}")

    print("\nDone.")


if __name__ == "__main__":
    main()