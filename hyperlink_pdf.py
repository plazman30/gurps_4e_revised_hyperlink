#!/usr/bin/env python3
"""
hyperlink_pdf.py -- Add clickable hyperlinks to in-text page references
in a PDF (e.g. "see p. 208", "(pp. 40-43)", or an Index's bare
"Accents, 24."), pointing them at the actual page they reference.

Works standalone, directly on your own copy of a PDF -- no separate
"already-linked" source file or lookup table needed. Everything this
script knows was learned the hard way, iterating against a real book:
  - Page-number scheme (roman front matter, arabic body) is detected
    by scanning footers, not hardcoded.
  - Handles several spacing variants publishers use between "p." and
    the number (narrow no-break space, regular space, non-breaking
    space), including when they end up as separate word tokens.
  - Detects an Index section (bare "Term, 24." style, no "p." prefix)
    separately from body-style "p. NNN" references.
  - Handles a page range that word-wraps across a line break (e.g.
    "418-" at the end of one line, "425," continuing the next) --
    links BOTH halves to the range's true start page.
  - Skips references that look like they cite a DIFFERENT book (e.g.
    "GURPS Powers, p. 40") rather than blindly linking any in-range
    number.
  - Never creates a link where one already exists -- this is what
    keeps it from touching a Table of Contents that already has its
    own (correct) native links, without needing to hardcode or detect
    a TOC page range at all.

USAGE:
    python3 hyperlink_pdf.py INPUT.pdf OUTPUT.pdf

REQUIREMENTS:
    pip install pymupdf

LIMITATIONS (please read before trusting the output blindly):
  - The "different book" detection looks for a trigger word (default
    "gurps") immediately followed by title-shaped text (capitalized
    words, no sentence-ending punctuation) right before a page
    reference. Change TITLE_TRIGGER_WORD below to adapt this to a
    different game line/publisher.
  - Only handles the "p."/"pp." abbreviation style for body references,
    and comma/semicolon-separated bare numbers for the Index. A book
    that spells out "page 208" instead will need REFERENCE_PATTERNS
    adjusted.
  - Index detection looks for the word "Index" in a page's
    footer/header band. A book that labels it differently (e.g.
    "Glossary") will need INDEX_HEADER_WORDS adjusted.
  - Doesn't touch font/text extraction quality -- if your PDF is a
    scan without embedded text, none of this will find anything.
"""

import sys
import re
import csv
import fitz  # PyMuPDF
from collections import Counter


NBSP = "\u202f"
OTHER_SPACES = " \u00a0\u2008"  # regular space, nbsp, punctuation space
TITLE_TRIGGER_WORD = "gurps"     # word that flags a DIFFERENT book's title
INDEX_HEADER_WORDS = {"index"}   # footer/header word(s) that mark an Index page
TITLE_CONNECTORS = {"and", "of", "the", "in", "for", "to", "a", "an", "or", "&"}
LOOKBACK_WORDS_FOR_TITLE = 10

PP_SINGLE = re.compile(
    r'^\W*?(pp?)\.[' + re.escape(OTHER_SPACES) + NBSP + r']?(\d{1,4})'
    r'(?:[\u2013\u2014-](\d{1,4}))?'
)
BARE_NUM = re.compile(r'^(\d{1,4})(?:[\u2013\u2014-](\d{1,4}))?[.,;)]*$')
WRAP_START = re.compile(r'^(\d{1,4})[\u2013\u2014-]$')
WRAP_CONT = re.compile(r'^(\d{1,4})')


# ---------------------------------------------------------------------------
# Page-numbering detection
# ---------------------------------------------------------------------------

def bottom_words(page, band=45):
    h = page.rect.height
    return [w for w in page.get_text("words") if w[3] > h - band]


def detect_page_labels(doc):
    """Scan footers to find the arabic body-page offset and valid range."""
    offsets = []
    arabic_numbers_seen = []

    for i in range(doc.page_count):
        tokens = [w[4].strip(".,") for w in bottom_words(doc[i])]
        for t in tokens:
            if t.isdigit():
                n = int(t)
                offsets.append(i - n)
                arabic_numbers_seen.append(n)

    if not offsets:
        raise RuntimeError(
            "Couldn't detect any page numbers in footers/headers -- "
            "this script assumes a printed page number appears near the "
            "top or bottom of most pages."
        )

    offset_counts = Counter(offsets)
    best_offset, _ = offset_counts.most_common(1)[0]
    valid_numbers = [n for n, off in zip(arabic_numbers_seen, offsets) if off == best_offset]
    return best_offset, (min(valid_numbers), max(valid_numbers))


def detect_index_pages(doc):
    """Pages whose footer/header band contains an Index marker word."""
    index_pages = set()
    for i in range(doc.page_count):
        tokens = {w[4].strip(".,:").lower() for w in bottom_words(doc[i])}
        if tokens & INDEX_HEADER_WORDS:
            index_pages.add(i)
    return index_pages


# ---------------------------------------------------------------------------
# Cross-book title detection
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Reference matching
# ---------------------------------------------------------------------------

def rects_meaningfully_overlap(a, b):
    """True only if these rects substantially overlap, not just touch at
    a shared edge. Adjacent lines' word bounding boxes routinely touch
    or overlap by a fraction of a point (tight line-leading), which
    made a plain rect.intersects() check produce false positives -- a
    reference would get incorrectly treated as 'already linked' because
    an unrelated reference on the line directly above or below happened
    to share a boundary pixel."""
    ix0, iy0 = max(a.x0, b.x0), max(a.y0, b.y0)
    ix1, iy1 = min(a.x1, b.x1), min(a.y1, b.y1)
    if ix1 <= ix0 or iy1 <= iy0:
        return False
    overlap_area = (ix1 - ix0) * (iy1 - iy0)
    a_area = max((a.x1 - a.x0) * (a.y1 - a.y0), 1e-6)
    return (overlap_area / a_area) > 0.5


def find_body_references(words):
    """'p. NNN' / 'pp. NNN-NNN' style references, any spacing variant."""
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
            num = int(m.group(2))
            refs.append((j, j, num))
            consumed.add(j)
            j += 1
            continue
        bare_tok = re.sub(r'^\W+', '', tok).lower()
        if bare_tok in ("p.", "pp.") and j + 1 < len(words):
            nm = re.match(r"^(\d{1,4})", words[j + 1][4])
            if nm:
                num = int(nm.group(1))
                refs.append((j, j + 1, num))
                consumed.add(j)
                consumed.add(j + 1)
                j += 2
                continue
        j += 1
    return refs, consumed


def find_index_references(words, h, already_consumed):
    """Bare 'Term, 24.' style references, plus line-wrapped ranges."""
    refs = []
    consumed = set(already_consumed)

    # wrapped ranges: "418-" at end of line, "425," continuing
    for i, w in enumerate(words):
        if i in consumed:
            continue
        m = WRAP_START.match(w[4])
        if not m or i + 1 >= len(words) or (i + 1) in consumed:
            continue
        if not WRAP_CONT.match(words[i + 1][4]):
            continue
        num = int(m.group(1))
        refs.append((i, i, num))
        refs.append((i + 1, i + 1, num))
        consumed.add(i)
        consumed.add(i + 1)

    # plain bare numbers (skip the page's own footer band)
    for i, w in enumerate(words):
        if i in consumed:
            continue
        if w[3] > h - 45:
            continue
        m = BARE_NUM.match(w[4])
        if not m:
            continue
        refs.append((i, i, int(m.group(1))))

    return refs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 hyperlink_pdf.py INPUT.pdf OUTPUT.pdf")
        sys.exit(1)

    in_path, out_path = sys.argv[1], sys.argv[2]
    report_path = out_path.rsplit(".", 1)[0] + "_link_report.csv"

    import shutil
    shutil.copyfile(in_path, out_path)
    doc = fitz.open(out_path)

    print("Detecting page-numbering scheme...")
    offset, valid_range = detect_page_labels(doc)
    print(f"  Body pages: printed {valid_range[0]}-{valid_range[1]}, "
          f"pdf_index = printed_number + {offset}")

    index_pages = detect_index_pages(doc)
    print(f"  Detected {len(index_pages)} Index page(s) "
          f"(header word match: {sorted(INDEX_HEADER_WORDS)})")

    def printed_to_index(n):
        idx = n + offset
        if valid_range[0] <= n <= valid_range[1]:
            return idx
        return None

    added, skipped_range, skipped_title, skipped_existing = 0, 0, 0, 0
    report_rows = []

    for i in range(doc.page_count):
        page = doc[i]
        words = page.get_text("words")
        existing_links = [l["from"] for l in page.get_links()]

        body_refs, consumed = find_body_references(words)
        all_refs = list(body_refs)
        if i in index_pages:
            all_refs += find_index_references(words, page.rect.height, consumed)

        for wi, wj, num in all_refs:
            rect = fitz.Rect(words[wi][0], words[wi][1], words[wj][2], words[wj][3])
            text = " ".join(w[4] for w in words[wi:wj + 1])

            if any(rects_meaningfully_overlap(rect, r) for r in existing_links):
                skipped_existing += 1
                continue

            title = title_nearby(words, wi)
            if title:
                skipped_title += 1
                report_rows.append((i + 1, text, num, "skipped", f"other-book title nearby: {title}"))
                continue

            target = printed_to_index(num)
            if target is None:
                skipped_range += 1
                report_rows.append((i + 1, text, num, "skipped", "out of page-number range"))
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

    doc.saveIncr()

    with open(report_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["PDF Page", "Matched Text", "Ref Number", "Status", "Detail"])
        writer.writerows(report_rows)

    print(f"\nAdded {added} links")
    print(f"Skipped {skipped_existing} (already linked, e.g. native TOC)")
    print(f"Skipped {skipped_title} (other-book title nearby)")
    print(f"Skipped {skipped_range} (out of page-number range)")
    print(f"Wrote {out_path}")
    print(f"Wrote report: {report_path}")


if __name__ == "__main__":
    main()
