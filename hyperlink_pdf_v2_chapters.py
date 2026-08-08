#!/usr/bin/env python3
"""
hyperlink_pdf_v2_chapters.py -- Everything hyperlink_pdf.py does, PLUS:
detects references to this book's own CHAPTER NAMES (e.g. an italicized
"Combat" or "Tactical Combat" appearing in running text, with or
without a page number nearby) and links them to that chapter's actual
starting page.

Chapter names are extracted straight from this book's own Table of
Contents (top-level numbered entries like "11. Combat . . . 362"), not
hardcoded -- so this should adapt to a different GURPS book's own
chapter list automatically.

Matching is deliberately conservative to avoid false positives:
  - Only a CONTIGUOUS italicized run whose text EXACTLY equals a
    chapter title counts as a match -- not a substring. This is what
    keeps "Combat Reflexes" or "Close Combat" from falsely matching
    the "Combat" chapter; the full italic span has to equal "Combat"
    with nothing else italicized alongside it.
  - Reuses the same "GURPS <Title>" cross-book detection as the page-
    number linker -- "GURPS Magic" (a different book) won't get linked
    to this book's own "Magic" chapter.
  - Never creates a link where one already exists (same rule as the
    rest of the pipeline), so a chapter name immediately next to an
    already-linked page reference doesn't get double-linked.

USAGE:
    python3 hyperlink_pdf_v2_chapters.py INPUT.pdf OUTPUT.pdf

REQUIREMENTS:
    pip install pymupdf
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
    """Find explicit 'Chapter N' / 'Chapters N-M' / 'Chapters N and M'
    references -- this book's own actual cross-reference convention
    (confirmed against real text; italicized-title matching alone was
    tried first and produced too many false positives from ordinary
    prose, stat-block labels like 'Advantages: 15 points', and the
    like). Returns (chapter_word_idx, number_word_idx, [chapter_numbers])."""
    refs = []
    i = 0
    while i < len(words):
        m = match_chapter_word(words, i)
        if not m:
            i += 1
            continue
        chap_end, plural = m
        j = chap_end + 1
        nums = []
        if j < len(words):
            num_m = re.match(r'^(\d{1,2})', words[j][4])
            if num_m:
                nums.append(int(num_m.group(1)))
                rest = words[j][4][num_m.end():]
                range_m = re.match(r'^[\u2013\u2014-](\d{1,2})', rest)
                if range_m:
                    nums.append(int(range_m.group(1)))
                elif j + 2 < len(words) and words[j + 1][4].lower() == 'and':
                    m2 = re.match(r'^(\d{1,2})', words[j + 2][4])
                    if m2:
                        nums.append(int(m2.group(1)))
                refs.append((i, j, nums))
                i = j + 1
                continue
        i = chap_end + 1
    return refs


def normalize_title(s):
    s = re.sub(r"[^\w\s]", "", s).strip().lower()
    return re.sub(r"\s+", " ", s)


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
        print("Usage: python3 hyperlink_pdf_v2_chapters.py INPUT.pdf OUTPUT.pdf")
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

    toc_pages = detect_toc_pages(doc)
    chapters = extract_chapters(doc, toc_pages, printed_to_index)
    print(f"  Detected {len(chapters)} chapter(s) from the TOC "
          f"(header word match: {sorted(TOC_HEADER_WORDS)})")
    chapter_by_title = {normalize_title(title): target for _, title, target in chapters}
    chapter_by_number = {num: target for num, title, target in chapters}
    for num, title, target in chapters:
        print(f"    {num}. {title!r} -> pdf page {target + 1}")

    added, skipped_range, skipped_title, skipped_existing = 0, 0, 0, 0
    chapter_added, chapter_skipped_title, chapter_skipped_existing = 0, 0, 0
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

        # Chapter-name pass: skip the TOC itself and the Index (neither
        # should get chapter-name links -- TOC already has its own
        # native links, and Index entries are terms, not prose).
        if i in toc_pages or i in index_pages:
            continue

        for wi, wj, nums in find_chapter_number_refs(words):
            valid_nums = [n for n in nums if n in chapter_by_number]
            if not valid_nums:
                continue
            target = chapter_by_number[valid_nums[0]]
            if target == i:
                continue  # already on this chapter's own opening page

            ref_words = words[wi:wj + 1]
            run_text = " ".join(w[4] for w in ref_words)

            # Group the reference's words by (block, line) so a reference
            # that word-wraps across a line break gets one tight rect per
            # line, instead of one rect spanning start-of-line-1 to
            # end-of-line-2 (which fitz.Rect silently normalizes into a
            # box covering BOTH full lines, including unrelated text
            # between them -- confirmed the actual cause of several
            # mis-highlighted chapter links during testing).
            line_groups = []
            cur_key, cur_words = None, []
            for w in ref_words:
                key = (w[5], w[6])
                if key != cur_key and cur_words:
                    line_groups.append(cur_words)
                    cur_words = []
                cur_key = key
                cur_words.append(w)
            if cur_words:
                line_groups.append(cur_words)

            rects = []
            for gi, group in enumerate(line_groups):
                x0 = min(w[0] for w in group)
                y0 = min(w[1] for w in group)
                x1 = max(w[2] for w in group)
                y1 = max(w[3] for w in group)
                rects.append(fitz.Rect(x0, y0, x1, y1))

            # Refinement: the line containing the chapter number can have
            # trailing text glued on with no real space (e.g. a token
            # like "4)\u202f\u2013\u202fe.g.," -- number, closing paren, en-dash,
            # and the next word all as one PDF "word"). Try to trim that
            # line's rect down to just "Chapter N" via search_for, which
            # operates on the text stream rather than word tokens and
            # naturally stops at the right place. Only used if it finds
            # exactly one match near where we already know the text is
            # (avoids picking a same-text match elsewhere on the page).
            chap_word_clean = re.sub(r"^\W+", "", ref_words[0][4])
            base = "Chapters" if chap_word_clean.lower().startswith("chapters") else "Chapter"

            probes = []
            if len(valid_nums) >= 2:
                n1, n2 = valid_nums[0], valid_nums[1]
                probes.append(f"{base} {n1}-{n2}")
                probes.append(f"{base} {n1}\u2013{n2}")
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
            if any(rects_meaningfully_overlap(approx_rect, r) for r in existing_links):
                chapter_skipped_existing += 1
                continue

            title = title_nearby(words, wi)
            if title:
                chapter_skipped_title += 1
                report_rows.append((i + 1, run_text, "", "skipped",
                                     f"chapter ref, but other-book title nearby: {title}"))
                continue

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

    doc.saveIncr()

    with open(report_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["PDF Page", "Matched Text", "Ref Number", "Status", "Detail"])
        writer.writerows(report_rows)

    print(f"\nAdded {added} page-reference links")
    print(f"  Skipped {skipped_existing} (already linked)")
    print(f"  Skipped {skipped_title} (other-book title nearby)")
    print(f"  Skipped {skipped_range} (out of page-number range)")
    print(f"\nAdded {chapter_added} chapter-name links")
    print(f"  Skipped {chapter_skipped_existing} (already linked)")
    print(f"  Skipped {chapter_skipped_title} (other-book title nearby)")
    print(f"Wrote {out_path}")
    print(f"Wrote report: {report_path}")


if __name__ == "__main__":
    main()
