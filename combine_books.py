#!/usr/bin/env python3
"""
Combine the GURPS 4E Basic Set PDFs into a single file.

- 1Characters is placed first, 2Campaigns second.
- Pages labeled 329-334 and 337 are removed from 1Characters (cut content,
  not part of the printed page-number sequence used by 2Campaigns).
- Pages labeled 339-341 (2Campaigns' table of contents) are moved to sit
  right after the page labeled 4 in 1Characters, to combine the two books'
  tables of contents.
- The page labeled I in 2Campaigns is moved to sit right after the matching
  I page in 1Characters.
- Both pages labeled II (1Characters' and 2Campaigns') are moved to the very
  end of the combined file.
- Every page before the page labeled 5 (in the final page order) is
  relabeled with sequential lowercase roman numerals (i, ii, iii, ...).
  All other pages keep the exact page label (as shown in a PDF viewer /
  printed on the page) they had in their source file.
- With --hyperlink, the combined file is also hyperlinked afterward: every
  in-text page/chapter reference gets linked to the right page, the same way
  hyperlink_pdf_universal.py does it for a single book. That script's
  own page-numbering detection (scan footers, assume one constant
  pdf_index-minus-printed-number offset for the whole book) doesn't work
  here -- splicing two separately-paginated books together produces
  several different offsets in one file, not one, so a huge fraction of
  references get wrongly rejected as "out of range." This script sidesteps
  that entirely: it already knows the true label for every output page
  (combined_labels, built and verified above), so page lookups are a
  direct dict, not a re-derived guess. The reference-matching logic itself
  (regexes, cross-book detection, rect safety checks) is copied from
  hyperlink_pdf_universal.py essentially unchanged -- see that file's
  history and CLAUDE.md for the bugs behind each piece of it.
"""

import argparse
import csv
import re

import fitz  # PyMuPDF
import pypdf

OUTPUT_PDF = "GURPS-4E-BasicSet-Combined_rgb.pdf"

# Page labels deleted from 1Characters.
DELETE_LABELS = {"329", "330", "331", "332", "333", "334", "337"}

# Page labels moved from 2Campaigns into 1Characters: for each entry, the
# listed 2Campaigns labels are inserted right after the matching 1Characters
# label, in the order given. Entries are applied in document order (by where
# the anchor label falls in 1Characters).
MOVES_FROM_CAMPAIGNS = {
    "I": ["I"],
    "4": ["339", "340", "341"],
}

# (source book, label) pairs relocated to the very end of the combined file,
# in the order they should appear there.
TAIL_MOVES = [
    ("characters", "II"),
    ("campaigns", "II"),
]

# Every page before this label (in the final page order) gets a sequential
# lowercase roman numeral label instead of its original label.
RELABEL_LOWERCASE_ROMAN_BEFORE = "5"

METADATA = {
    "/Title": "GURPS 4th Edition Basic Set Combined",
    "/Author": "Steve Jackson Games",
    "/Subject": "GURPS",
}

# Title of the bookmark whose target page becomes the file's initial view
# (/OpenAction), i.e. the page shown when the PDF is first opened.
OPEN_TO_BOOKMARK = "Contents"

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_ROMAN_NUMERALS = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]


def int_to_roman(num: int) -> str:
    result = []
    for value, symbol in _ROMAN_NUMERALS:
        while num >= value:
            result.append(symbol)
            num -= value
    return "".join(result)


def roman_to_int(label: str) -> int:
    total = 0
    prev_value = 0
    for ch in reversed(label.upper()):
        value = _ROMAN_VALUES[ch]
        total += value if value >= prev_value else -value
        prev_value = value
    return total


def label_style(label: str) -> str:
    """Return '/D', '/R' (uppercase roman), or '/r' (lowercase roman)."""
    if label.isdigit():
        return "/D"
    if label and set(label) <= set(_ROMAN_VALUES):
        return "/R"
    if label and set(label.upper()) <= set(_ROMAN_VALUES) and label == label.lower():
        return "/r"
    raise ValueError(f"Unrecognized page label style: {label!r}")


def numeric_value(label: str) -> int:
    return int(label) if label.isdigit() else roman_to_int(label)


# ---------------------------------------------------------------------------
# Hyperlinking logic, ported from hyperlink_pdf_universal.py.
#
# Everything below down to add_hyperlinks() is the same reference-matching,
# cross-book-detection, and rect-safety logic as that script -- copied
# rather than imported, since this is a one-off pipeline for exactly one
# merged file and shouldn't depend on hyperlink_pdf_universal.py staying
# unchanged. The ONE thing deliberately left out is detect_page_labels():
# that function assumes a single constant (pdf_index - printed_number)
# offset holds for the whole document, which is false here by construction
# (see the module docstring above) -- add_hyperlinks() below replaces it
# with a direct lookup from combined_labels instead.
# ---------------------------------------------------------------------------

NBSP = " "
OTHER_SPACES = "   "  # regular space, nbsp, punctuation space
DEFAULT_TRIGGER_WORD = "gurps"   # fallback if title-based auto-detection below fails
TITLE_TRIGGER_WORD = DEFAULT_TRIGGER_WORD
_TRIGGER_STOPWORDS = {"the", "a", "an", "of", "and"}


def detect_title_trigger_word(doc):
    """Derive the word that flags a reference to a DIFFERENT book from this
    PDF's OWN title metadata (e.g. 'GURPS 4th Edition Basic Set Combined'
    -> 'gurps'), instead of a hardcoded brand name."""
    title = (doc.metadata or {}).get("title", "") or ""
    words = [w.lower() for w in re.findall(r"[A-Za-z']+", title)]
    words = [w for w in words if w not in _TRIGGER_STOPWORDS]
    return words[0] if words else None


INDEX_HEADER_WORDS = {"index"}   # footer/header word(s) that mark an Index page
TITLE_CONNECTORS = {"and", "of", "the", "in", "for", "to", "a", "an", "or", "&"}
LOOKBACK_WORDS_FOR_TITLE = 10

PP_SINGLE = re.compile(
    r'^\W*?(pp?)\.[' + re.escape(OTHER_SPACES) + NBSP + r']?([A-Z]{1,3})?(\d{1,4})'
    r'(?:[–—-]([A-Z]{1,3})?(\d{1,4}))?'
)
BARE_NUM = re.compile(r'^(\d{1,4})(?:[–—-](\d{1,4}))?[.,;)]*$')
WRAP_START = re.compile(r'^(\d{1,4})[–—-]$')
WRAP_CONT = re.compile(r'^(\d{1,4})')

# GURPS's own formal cross-reference shorthand: a page reference prefixed
# with a book-code letter (or short letter combo) means "this page in a
# DIFFERENT book" -- e.g. "p. B123" = Basic Set p.123. Any such code is
# always treated as cross-book, regardless of which letter.
BOOK_CODE_TOKEN = re.compile(r'^([A-Z]{1,3})(\d{1,4})')


def bottom_words(page, band=45):
    h = page.rect.height
    return [w for w in page.get_text("words") if w[3] > h - band]


def detect_index_pages(doc):
    """Pages whose footer/header band contains an Index marker word."""
    index_pages = set()
    for i in range(doc.page_count):
        tokens = {w[4].strip(".,:").lower() for w in bottom_words(doc[i])}
        if tokens & INDEX_HEADER_WORDS:
            index_pages.add(i)
    return index_pages


TOC_HEADER_WORDS = {"contents"}


def detect_toc_pages(doc):
    toc_pages = set()
    for i in range(doc.page_count):
        tokens = {w[4].strip(".,:").lower() for w in bottom_words(doc[i])}
        if tokens & TOC_HEADER_WORDS:
            toc_pages.add(i)
    return toc_pages


def extract_chapters(doc, toc_pages, printed_to_index):
    """Pull (chapter_number, title, target_pdf_index) from this book's
    own TOC -- top-level entries are lines whose first word is a lone
    'N.' (e.g. '11. Combat . . . 362')."""
    from collections import defaultdict

    chapters = []
    for i in sorted(toc_pages):
        page = doc[i]
        words = page.get_text("words")
        lines = defaultdict(list)
        for w in words:
            lines[(w[5], w[6])].append(w)
        sorted_keys = sorted(lines.keys())
        line_word_lists = [sorted(lines[k], key=lambda w: w[0]) for k in sorted_keys]

        def strip_trailing_number(tw):
            while tw and re.match(r'^\.+$', tw[-1]):
                tw = tw[:-1]
            if tw and tw[-1].strip(".,").isdigit():
                return tw[:-1], tw[-1].strip(".,")
            return tw, None

        idx = 0
        while idx < len(line_word_lists):
            ws = line_word_lists[idx]
            first = ws[0][4]
            m = re.match(r'^(\d{1,2})\.$', first)
            if not m:
                idx += 1
                continue
            title_words = [w[4] for w in ws[1:]]
            clean, pagenum = strip_trailing_number(title_words)
            scan_idx = idx
            while pagenum is None and scan_idx + 1 < len(line_word_lists):
                scan_idx += 1
                nxt_words = [w[4] for w in line_word_lists[scan_idx]]
                nclean, npagenum = strip_trailing_number(nxt_words)
                clean += nclean
                pagenum = npagenum
                if scan_idx - idx > 3:
                    break

            title = " ".join(w for w in clean if not re.match(r'^\.+$', w))
            title = re.sub(r"\s+", " ", title).strip(" .")
            if pagenum and title:
                target = printed_to_index(int(pagenum))
                if target is not None:
                    chapters.append((int(m.group(1)), title, target))
            idx = scan_idx + 1

    return chapters


def find_toc_page_number_words(page):
    """For each visual line on a TOC page, find the trailing word if it's
    a bare page number (the typical 'Title . . . . 36' dot-leader
    format). Returns list of (word_idx, page_number). Excludes the
    page's own footer band."""
    from collections import defaultdict
    words = page.get_text("words")
    h = page.rect.height
    lines = defaultdict(list)
    for idx, w in enumerate(words):
        if w[3] > h - 45:
            continue
        lines[(w[5], w[6])].append((idx, w))

    results = []
    for key in sorted(lines.keys()):
        ws = sorted(lines[key], key=lambda p: p[1][0])
        last_idx, last_w = ws[-1]
        num_str = last_w[4].strip(".,")
        if num_str.isdigit():
            results.append((last_idx, int(num_str)))
    return results, words


def toc_already_hyperlinked(doc, toc_pages):
    """Compare how many TOC lines look like page-number entries against
    how many existing links are actually there -- if links cover less
    than half of the apparent entries, treat the TOC as unlinked."""
    if not toc_pages:
        return True
    candidate_count = 0
    link_count = 0
    for i in toc_pages:
        page = doc[i]
        entries, _ = find_toc_page_number_words(page)
        candidate_count += len(entries)
        link_count += len(page.get_links())
    if candidate_count == 0:
        return True
    return link_count >= candidate_count * 0.5


CHAPTER_WORD_PAT = re.compile(r'^\W*(Chapters?)$')
CHAPTER_HYPHEN_START_PAT = re.compile(r'^\W*Chap\w*[\xad-]$')  # e.g. 'Chap\xad' or 'Chapt-'


def match_chapter_word(words, i):
    """Detect a 'Chapter'/'Chapters' token starting at index i, which may
    have leading punctuation attached ('(Chapter') or be split across a
    line-wrap hyphen ('Chap\xad' + 'ter'). Returns (end_idx, plural) or None."""
    tok = words[i][4]
    m = CHAPTER_WORD_PAT.match(tok)
    if m:
        return i, m.group(1).endswith("s")
    if CHAPTER_HYPHEN_START_PAT.match(tok) and i + 1 < len(words):
        stripped = re.sub(r"^\W+", "", tok)
        combined = re.sub(r"[\xad-]$", "", stripped) + words[i + 1][4]
        m2 = re.match(r"^(Chapters?)\b", combined)
        if m2:
            return i + 1, m2.group(1).endswith("s")
    return None


def find_chapter_number_refs(words):
    """Find explicit 'Chapter N' / 'Chapters N-M' / 'Chapters N and M' /
    'Chapters N, M, and L' references. Returns (chapter_word_idx,
    end_word_idx, groups) where groups is a list of (word_idx, [numbers])
    -- one entry per distinct word position."""
    refs = []
    i = 0
    while i < len(words):
        m = match_chapter_word(words, i)
        if not m:
            i += 1
            continue
        chap_end, plural = m
        j = chap_end + 1
        if j >= len(words):
            i = chap_end + 1
            continue
        num_m = re.match(r'^(\d{1,2})', words[j][4])
        if not num_m:
            i = chap_end + 1
            continue

        groups = [(j, [int(num_m.group(1))])]
        rest = words[j][4][num_m.end():]
        end_idx = j

        range_m = re.match(r'^[–—-](\d{1,2})', rest)
        if range_m:
            groups[0][1].append(int(range_m.group(1)))
        else:
            # Comma/and-separated list: "2, 4, and 6" or "2, 4, 6".
            k = j + 1
            while k < len(words):
                tok = words[k][4]
                if tok.lower() == "and" and k + 1 < len(words):
                    m2 = re.match(r'^(\d{1,2})', words[k + 1][4])
                    if m2:
                        groups.append((k + 1, [int(m2.group(1))]))
                        end_idx = k + 1
                        k += 2
                        continue
                    break
                m3 = re.match(r'^(\d{1,2}),?$', tok)
                if m3:
                    groups.append((k, [int(m3.group(1))]))
                    end_idx = k
                    k += 1
                    continue
                break

        refs.append((i, end_idx, groups))
        i = end_idx + 1
    return refs


def normalize_title(s):
    s = re.sub(r"[^\w\s]", "", s).strip().lower()
    return re.sub(r"\s+", " ", s)


def looks_like_title_span(words):
    for w in words:
        bare = w.strip(",;:")
        if not bare:
            continue
        if bare.lower() in TITLE_CONNECTORS:
            continue
        if not (bare[0].isupper() or bare[0].isdigit()):
            return False
        if "." in bare[:-1]:
            return False
    return True


def title_nearby(words, ref_word_idx):
    """If a '<TRIGGER> <Title...>' run sits immediately before this
    reference, return the matched text (signal to skip linking)."""
    lo = max(0, ref_word_idx - LOOKBACK_WORDS_FOR_TITLE)
    span = words[lo:ref_word_idx]
    for start in range(len(span)):
        bare_tok = span[start][4].strip("(),;:").lower()
        if bare_tok == TITLE_TRIGGER_WORD:
            between = span[start + 1:]
            if looks_like_title_span([w[4] for w in between]):
                return " ".join(w[4] for w in span[start:])
    return None


def build_italic_spans(page):
    spans = []
    d = page.get_text("dict")
    for b in d["blocks"]:
        if "lines" not in b:
            continue
        for l in b["lines"]:
            for s in l["spans"]:
                spans.append((fitz.Rect(s["bbox"]), bool(s["flags"] & 2)))
    return spans


def word_is_italic(rect, spans):
    cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
    for r, italic in spans:
        if r.x0 - 0.5 <= cx <= r.x1 + 0.5 and r.y0 - 0.5 <= cy <= r.y1 + 0.5:
            return italic
    return False


def build_same_book_vocabulary(doc, toc_pages, index_pages):
    """This book's own section titles + Index terms, normalized. Used to
    tell 'this italicized phrase is part of THIS book' from 'this
    italicized phrase names some OTHER book.'"""
    vocab = set()

    for i in toc_pages:
        page = doc[i]
        words = page.get_text("words")
        from collections import defaultdict
        lines = defaultdict(list)
        for w in words:
            lines[(w[5], w[6])].append(w)
        for key in sorted(lines.keys()):
            ws = sorted(lines[key], key=lambda w: w[0])
            text_words = [w[4] for w in ws if not w[4].strip(".,").isdigit()]
            title = " ".join(text_words).strip(" .")
            norm = normalize_title(title)
            if len(norm) > 2:
                vocab.add(norm)

    for i in index_pages:
        page = doc[i]
        text = page.get_text()
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^([A-Za-z][A-Za-z0-9 ,'\"\-/&]*?)(?:,?\s*\d)", line)
            if m:
                norm = normalize_title(m.group(1))
                if len(norm) > 2:
                    vocab.add(norm)

    return vocab


# Known GURPS 4th-edition product titles that get cited by name alone (no
# "GURPS" prefix). Necessarily incomplete, but that's the safe failure
# mode -- an unrecognized title just falls through as same-book.
KNOWN_GURPS_TITLES = {
    "basic set", "characters", "campaigns",
    "low-tech", "high-tech", "ultra-tech", "bio-tech",
    "dungeon fantasy", "powers", "magic", "psionic powers",
    "martial arts", "horror", "space", "social engineering",
    "zombies", "monster hunters", "action", "banestorm",
    "infinite worlds", "thaumatology", "mysteries", "supers",
    "traveller", "template toolkit", "power-ups", "pyramid",
    "gun fu", "vehicles", "steampunk",
}


KNOWN_GURPS_TITLES_NORM = {normalize_title(t) for t in KNOWN_GURPS_TITLES}


def italic_title_nearby(words, spans, ref_word_idx, vocab):
    """Look immediately before the reference for a contiguous italicized
    run that matches a KNOWN other GURPS product title."""
    i = ref_word_idx - 1
    while i >= 0 and words[i][4].strip("(),.;:").lower() in ("(", "see", "cf."):
        i -= 1
    run = []
    steps = 0
    while i >= 0 and steps < LOOKBACK_WORDS_FOR_TITLE:
        rect = fitz.Rect(words[i][0], words[i][1], words[i][2], words[i][3])
        if word_is_italic(rect, spans):
            run.append(words[i][4])
            i -= 1
            steps += 1
        else:
            break
    if not run:
        return None
    phrase = " ".join(reversed(run)).strip(" ,.;:()")
    if normalize_title(phrase) in KNOWN_GURPS_TITLES_NORM:
        return phrase
    return None


MAX_LINK_HEIGHT = 40   # a link should never span more than ~triple a line
MAX_LINK_WIDTH_FRAC = 0.9  # or more than ~a full line's width


def is_reasonable_link_rect(rect, page):
    """Safety net: reject rects that are implausibly large for a short
    text reference (a rare PDF text-extraction anomaly)."""
    if rect.height > MAX_LINK_HEIGHT:
        return False
    if rect.width > page.rect.width * MAX_LINK_WIDTH_FRAC:
        return False
    return True


def rects_meaningfully_overlap(a, b):
    """True only if these rects substantially overlap, not just touch at
    a shared edge (a plain rect.intersects() check produces false
    positives from adjacent lines' word bounding boxes touching)."""
    ix0, iy0 = max(a.x0, b.x0), max(a.y0, b.y0)
    ix1, iy1 = min(a.x1, b.x1), min(a.y1, b.y1)
    if ix1 <= ix0 or iy1 <= iy0:
        return False
    overlap_area = (ix1 - ix0) * (iy1 - iy0)
    a_area = max((a.x1 - a.x0) * (a.y1 - a.y0), 1e-6)
    return (overlap_area / a_area) > 0.5


def find_body_references(words):
    """'p. NNN' / 'pp. NNN-NNN' style references, any spacing variant.
    Returns (start_idx, end_idx, number, book_code, range_end)."""
    refs = []
    consumed = set()
    j = 0
    while j < len(words):
        if j in consumed:
            j += 1
            continue
        tok = words[j][4]
        m = PP_SINGLE.match(tok)
        if m:
            code = m.group(2)
            num = int(m.group(3))
            num2 = int(m.group(5)) if m.group(5) else None
            refs.append((j, j, num, code, num2))
            consumed.add(j)
            j += 1
            continue
        bare_tok = re.sub(r'^\W+', '', tok).lower()
        if bare_tok in ("p.", "pp.") and j + 1 < len(words):
            nxt = words[j + 1][4]
            code_m = BOOK_CODE_TOKEN.match(nxt)
            if code_m:
                refs.append((j, j + 1, int(code_m.group(2)), code_m.group(1), None))
                consumed.add(j)
                consumed.add(j + 1)
                j += 2
                continue
            range_m = re.match(r'^(\d{1,4})[–—-](\d{1,4})', nxt)
            if range_m:
                num = int(range_m.group(1))
                num2 = int(range_m.group(2))
                refs.append((j, j + 1, num, None, num2))
                consumed.add(j)
                consumed.add(j + 1)
                j += 2
                continue
            nm = re.match(r"^(\d{1,4})", nxt)
            if nm:
                num = int(nm.group(1))
                refs.append((j, j + 1, num, None, None))
                consumed.add(j)
                consumed.add(j + 1)
                j += 2
                continue
        j += 1
    return refs, consumed


def find_index_references(words, h, already_consumed):
    """Bare 'Term, 24.' style references, plus line-wrapped ranges.
    Returns 5-tuples matching find_body_references' shape."""
    refs = []
    consumed = set(already_consumed)

    for i, w in enumerate(words):
        if i in consumed:
            continue
        m = WRAP_START.match(w[4])
        if not m or i + 1 >= len(words) or (i + 1) in consumed:
            continue
        cont_m = WRAP_CONT.match(words[i + 1][4])
        if not cont_m:
            continue
        num = int(m.group(1))
        refs.append((i, i, num, None, None))
        refs.append((i + 1, i + 1, num, None, None))
        consumed.add(i)
        consumed.add(i + 1)

    for i, w in enumerate(words):
        if i in consumed:
            continue
        if w[3] > h - 45:
            continue
        m = BARE_NUM.match(w[4])
        if not m:
            continue
        num2 = int(m.group(2)) if m.group(2) else None
        refs.append((i, i, int(m.group(1)), None, num2))

    return refs


def add_hyperlinks(output_path, combined_labels):
    """Second pass over the just-written, already-verified combined PDF:
    detect and insert page/chapter reference hyperlinks. The only real
    difference from hyperlink_pdf_universal.py's approach is how a printed
    page number resolves to a pdf page index -- this uses combined_labels
    (already built and verified above) as a direct dict instead of
    re-deriving numbering from footer text under a single-offset
    assumption, which is what breaks on a file spliced together from two
    separately-paginated books (see the module docstring)."""
    report_path = output_path.rsplit(".", 1)[0] + "_link_report.csv"

    doc = fitz.open(output_path)

    global TITLE_TRIGGER_WORD
    TITLE_TRIGGER_WORD = DEFAULT_TRIGGER_WORD
    detected_trigger = detect_title_trigger_word(doc)
    if detected_trigger:
        TITLE_TRIGGER_WORD = detected_trigger
        print(f"Cross-book trigger word (from this PDF's own title): {TITLE_TRIGGER_WORD!r}")
    else:
        print(f"Could not read a title from this PDF's metadata -- "
              f"falling back to {TITLE_TRIGGER_WORD!r}.")

    label_to_index = {
        int(label): i for i, label in enumerate(combined_labels) if label.isdigit()
    }
    print(f"Page-number lookup built directly from combined_labels: "
          f"{len(label_to_index)} arabic-labeled pages.")

    def printed_to_index(n):
        return label_to_index.get(n)

    index_pages = detect_index_pages(doc)
    print(f"  Detected {len(index_pages)} Index page(s) "
          f"(header word match: {sorted(INDEX_HEADER_WORDS)})")

    toc_pages = detect_toc_pages(doc)
    chapters = extract_chapters(doc, toc_pages, printed_to_index)
    print(f"  Detected {len(chapters)} chapter(s) from the TOC "
          f"(header word match: {sorted(TOC_HEADER_WORDS)})")
    chapter_by_number = {num: target for num, title, target in chapters}
    for num, title, target in chapters:
        print(f"    {num}. {title!r} -> pdf page {target + 1}")

    same_book_vocab = build_same_book_vocabulary(doc, toc_pages, index_pages)
    print(f"  Built same-book vocabulary: {len(same_book_vocab)} terms "
          f"(from TOC + Index) -- used to catch other-book titles cited "
          f"without the {TITLE_TRIGGER_WORD!r} trigger word")

    added, skipped_range, skipped_title, skipped_existing = 0, 0, 0, 0
    chapter_added, chapter_skipped_title = 0, 0
    toc_added = 0
    report_rows = []

    if toc_pages and not toc_already_hyperlinked(doc, toc_pages):
        print("  TOC has no (or very few) existing links -- adding them...")
        for i in toc_pages:
            page = doc[i]
            existing_links = [l["from"] for l in page.get_links()]
            entries, toc_words = find_toc_page_number_words(page)
            for word_idx, num in entries:
                target = printed_to_index(num)
                if target is None:
                    continue
                w = toc_words[word_idx]
                rect = fitz.Rect(w[0], w[1], w[2], w[3])
                if any(rects_meaningfully_overlap(rect, r) for r in existing_links):
                    continue
                if not is_reasonable_link_rect(rect, page):
                    continue
                page.insert_link({
                    "kind": fitz.LINK_GOTO,
                    "page": target,
                    "from": rect,
                    "to": fitz.Point(0, 0),
                })
                existing_links.append(rect)
                toc_added += 1
                report_rows.append((i + 1, w[4], num, "added (TOC entry)", f"pdf page {target + 1}"))
        print(f"  Added {toc_added} TOC links")
    elif toc_pages:
        print("  TOC already has links -- leaving it alone")

    for i in range(doc.page_count):
        page = doc[i]
        words = page.get_text("words")
        existing_links = [l["from"] for l in page.get_links()]
        italic_spans = build_italic_spans(page)

        body_refs, consumed = find_body_references(words)
        all_refs = list(body_refs)
        if i in index_pages:
            all_refs += find_index_references(words, page.rect.height, consumed)

        for wi, wj, num, book_code, range_end in all_refs:
            rect = fitz.Rect(words[wi][0], words[wi][1], words[wj][2], words[wj][3])
            text = " ".join(w[4] for w in words[wi:wj + 1])

            if any(rects_meaningfully_overlap(rect, r) for r in existing_links):
                skipped_existing += 1
                continue

            if book_code:
                skipped_title += 1
                report_rows.append((i + 1, text, num, "skipped",
                                     f"GURPS cross-book code {book_code!r} (e.g. p. {book_code}{num})"))
                continue

            title = title_nearby(words, wi)
            if title:
                skipped_title += 1
                report_rows.append((i + 1, text, num, "skipped", f"other-book title nearby: {title}"))
                continue

            italic_title = italic_title_nearby(words, italic_spans, wi, same_book_vocab)
            if italic_title:
                skipped_title += 1
                report_rows.append((i + 1, text, num, "skipped",
                                     f"italicized other-book title nearby (no vocab match): {italic_title}"))
                continue

            target = printed_to_index(num)
            if target is None:
                skipped_range += 1
                report_rows.append((i + 1, text, num, "skipped",
                                     "no page in this combined file has that printed number"))
                continue

            clean_start = re.sub(r"^\W+", "", text).lower()
            base = "pp" if clean_start.startswith("pp") else "p"
            probes = []
            if range_end is not None:
                probes.append(f"{base}.{NBSP}{num}-{range_end})")
                probes.append(f"{base}.{NBSP}{num}–{range_end})")
                probes.append(f"{base}.{NBSP}{num}-{range_end}")
                probes.append(f"{base}.{NBSP}{num}–{range_end}")
            probes.append(f"{base}.{NBSP}{num})")
            probes.append(f"{base}.{NBSP}{num}")
            for probe in probes:
                found = page.search_for(probe)
                near = [r for r in found if abs(r.y0 - rect.y0) < 2]
                if near:
                    rect = near[0]
                    break

            if not is_reasonable_link_rect(rect, page):
                skipped_range += 1
                report_rows.append((i + 1, text, num, "skipped",
                                     "rejected: implausibly large link rect (likely a source PDF text-extraction anomaly)"))
                continue

            page.insert_link({
                "kind": fitz.LINK_GOTO,
                "page": target,
                "from": rect,
                "to": fitz.Point(0, 0),
            })
            existing_links.append(rect)
            added += 1
            report_rows.append((i + 1, text, num, "added", f"pdf page {target + 1}"))

        if i in toc_pages or i in index_pages:
            continue

        for wi, end_idx, groups in find_chapter_number_refs(words):
            primary_word_idx, primary_nums = groups[0]
            valid_nums = [n for n in primary_nums if n in chapter_by_number]
            if not valid_nums:
                continue
            target = chapter_by_number[valid_nums[0]]

            ref_words = words[wi:end_idx + 1]
            run_text = " ".join(w[4] for w in ref_words)

            chap_word_clean = re.sub(r"^\W+", "", words[wi][4])
            base = "Chapters" if chap_word_clean.lower().startswith("chapters") else "Chapter"

            title = title_nearby(words, wi)
            italic_title = None if title else italic_title_nearby(words, italic_spans, wi, same_book_vocab)
            if title or italic_title:
                chapter_skipped_title += 1
                which = title or italic_title
                report_rows.append((i + 1, run_text, "", "skipped",
                                     f"chapter ref, but other-book title nearby: {which}"))
                continue

            if target != i:
                primary_span = words[wi:primary_word_idx + 1]
                line_groups = []
                cur_key, cur_words = None, []
                for w in primary_span:
                    key = (w[5], w[6])
                    if key != cur_key and cur_words:
                        line_groups.append(cur_words)
                        cur_words = []
                    cur_key = key
                    cur_words.append(w)
                if cur_words:
                    line_groups.append(cur_words)

                rects = []
                for group in line_groups:
                    x0 = min(w[0] for w in group)
                    y0 = min(w[1] for w in group)
                    x1 = max(w[2] for w in group)
                    y1 = max(w[3] for w in group)
                    rects.append(fitz.Rect(x0, y0, x1, y1))

                probes = []
                if len(valid_nums) >= 2:
                    n1, n2 = valid_nums[0], valid_nums[1]
                    probes.append(f"{base} {n1}-{n2}")
                    probes.append(f"{base} {n1}–{n2}")
                    probes.append(f"{base} {n1} and {n2}")
                probes.append(f"{base} {valid_nums[0]}")

                for probe in probes:
                    found = page.search_for(probe)
                    probe_hits = [r for r in found if any(
                        abs(r.y0 - g.y0) < 2 for g in rects
                    )]
                    if probe_hits:
                        rects = probe_hits
                        break

                approx_rect = fitz.Rect(
                    min(r.x0 for r in rects), min(r.y0 for r in rects),
                    max(r.x1 for r in rects), max(r.y1 for r in rects),
                )
                if (all(is_reasonable_link_rect(r, page) for r in rects)
                        and not any(rects_meaningfully_overlap(approx_rect, r) for r in existing_links)):
                    for rect in rects:
                        page.insert_link({
                            "kind": fitz.LINK_GOTO,
                            "page": target,
                            "from": rect,
                            "to": fitz.Point(0, 0),
                        })
                    existing_links.append(approx_rect)
                    chapter_added += 1
                    report_rows.append((i + 1, run_text, "", "added (chapter ref)", f"pdf page {target + 1}"))

            for word_idx, nums in groups[1:]:
                extra_valid = [n for n in nums if n in chapter_by_number]
                if not extra_valid:
                    continue
                extra_target = chapter_by_number[extra_valid[0]]
                if extra_target == i:
                    continue
                w = words[word_idx]
                extra_rect = fitz.Rect(w[0], w[1], w[2], w[3])
                probe = re.sub(r"^\W+", "", w[4])
                probe = re.match(r"^\d{1,2}", probe)
                if probe:
                    found = page.search_for(probe.group(0))
                    near = [r for r in found if abs(r.y0 - extra_rect.y0) < 2]
                    if near:
                        extra_rect = near[0]
                if not is_reasonable_link_rect(extra_rect, page):
                    continue
                if any(rects_meaningfully_overlap(extra_rect, r) for r in existing_links):
                    continue
                page.insert_link({
                    "kind": fitz.LINK_GOTO,
                    "page": extra_target,
                    "from": extra_rect,
                    "to": fitz.Point(0, 0),
                })
                existing_links.append(extra_rect)
                chapter_added += 1
                report_rows.append((i + 1, w[4], "", "added (chapter ref, list member)",
                                     f"pdf page {extra_target + 1}"))

    doc.saveIncr()

    with open(report_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["PDF Page", "Matched Text", "Ref Number", "Status", "Detail"])
        writer.writerows(report_rows)

    print(f"\nAdded {added} page-reference links")
    print(f"  Skipped {skipped_existing} (already linked)")
    print(f"  Skipped {skipped_title} (other-book title nearby)")
    print(f"  Skipped {skipped_range} (no matching printed page number in this file)")
    print(f"\nAdded {chapter_added} chapter-name links")
    print(f"  Skipped {chapter_skipped_title} (other-book title nearby)")
    print(f"\nAdded {toc_added} Table of Contents links")
    print(f"Wrote report: {report_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("characters_pdf", help="Path to the 1Characters PDF")
    parser.add_argument("campaigns_pdf", help="Path to the 2Campaigns PDF")
    parser.add_argument(
        "-o",
        "--output",
        default=OUTPUT_PDF,
        help=f"Output PDF path (default: {OUTPUT_PDF})",
    )
    parser.add_argument(
        "--hyperlink",
        action="store_true",
        help="After combining, also hyperlink in-text page/chapter references "
             "in the merged file (see add_hyperlinks()). Off by default -- "
             "without this flag, the output is just the combined PDF with no "
             "added links.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    characters = pypdf.PdfReader(args.characters_pdf)
    campaigns = pypdf.PdfReader(args.campaigns_pdf)

    char_labels = characters.page_labels
    camp_labels = campaigns.page_labels

    char_tail_labels = {label for book, label in TAIL_MOVES if book == "characters"}
    camp_tail_labels = {label for book, label in TAIL_MOVES if book == "campaigns"}

    char_keep_indices = [
        i
        for i, label in enumerate(char_labels)
        if label not in DELETE_LABELS and label not in char_tail_labels
    ]
    assert len(char_keep_indices) == len(char_labels) - len(DELETE_LABELS) - len(
        char_tail_labels
    )

    all_moved_camp_labels = {
        label for labels in MOVES_FROM_CAMPAIGNS.values() for label in labels
    }
    camp_keep_indices = [
        i
        for i, label in enumerate(camp_labels)
        if label not in all_moved_camp_labels and label not in camp_tail_labels
    ]
    assert len(camp_keep_indices) == len(camp_labels) - len(
        all_moved_camp_labels
    ) - len(camp_tail_labels)

    # Walk 1Characters' kept pages in order, splicing in the matching
    # 2Campaigns pages right after each anchor label.
    segments: list[tuple[pypdf.PdfReader, list[int]]] = []
    char_run: list[int] = []
    for idx in char_keep_indices:
        char_run.append(idx)
        label = char_labels[idx]
        if label in MOVES_FROM_CAMPAIGNS:
            segments.append((characters, char_run))
            char_run = []
            move_indices = [
                camp_labels.index(l) for l in MOVES_FROM_CAMPAIGNS[label]
            ]
            segments.append((campaigns, move_indices))
    if char_run:
        segments.append((characters, char_run))

    # Rest of 2Campaigns, minus the moved pages.
    segments.append((campaigns, camp_keep_indices))

    # Pages relocated to the very end of the file.
    for book, label in TAIL_MOVES:
        reader = characters if book == "characters" else campaigns
        labels = char_labels if book == "characters" else camp_labels
        segments.append((reader, [labels.index(label)]))

    writer = pypdf.PdfWriter()
    combined_labels: list[str] = []
    for reader, indices in segments:
        if not indices:
            continue
        writer.append(reader, pages=indices)
        source_labels = char_labels if reader is characters else camp_labels
        combined_labels.extend(source_labels[i] for i in indices)

    assert len(combined_labels) == len(writer.pages)

    # Relabel every page before RELABEL_LOWERCASE_ROMAN_BEFORE with
    # sequential lowercase roman numerals.
    boundary = combined_labels.index(RELABEL_LOWERCASE_ROMAN_BEFORE)
    for i in range(boundary):
        combined_labels[i] = int_to_roman(i + 1).lower()

    # Re-derive contiguous /PageLabels ranges (style + start value) for the
    # writer from the (possibly relabeled) sequence above. Labels are kept
    # as-is otherwise, even where this makes the sequence non-monotonic
    # (e.g. ...4, 339, 5...).
    range_start = 0
    for i in range(1, len(combined_labels) + 1):
        prev = combined_labels[i - 1]
        cur = combined_labels[i] if i < len(combined_labels) else None

        same_run = (
            cur is not None
            and label_style(prev) == label_style(cur)
            and numeric_value(cur) == numeric_value(prev) + 1
        )

        if not same_run:
            style = label_style(prev)
            start_value = numeric_value(combined_labels[range_start])
            writer.set_page_label(range_start, i - 1, style=style, start=start_value)
            range_start = i

    writer.add_metadata(METADATA)

    # Open the file to the combined table of contents rather than page one.
    contents_item = next(
        item
        for item in writer.outline
        if not isinstance(item, list) and item.title == OPEN_TO_BOOKMARK
    )
    open_page_index = writer.get_destination_page_number(contents_item)
    writer.open_destination = writer.pages[open_page_index]

    writer.write(args.output)

    # Verify the resulting labels and metadata match exactly what was intended.
    check = pypdf.PdfReader(args.output)
    assert check.page_labels == combined_labels, "Page labels do not match!"
    assert check.metadata.title == METADATA["/Title"]
    assert check.metadata.author == METADATA["/Author"]
    assert check.metadata.subject == METADATA["/Subject"]
    print(f"Wrote {args.output}: {len(writer.pages)} pages.")

    if args.hyperlink:
        print("\nHyperlinking the combined file...")
        add_hyperlinks(args.output, combined_labels)


if __name__ == "__main__":
    main()
