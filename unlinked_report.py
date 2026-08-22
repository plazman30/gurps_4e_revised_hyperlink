"""
Report every page-reference-looking piece of text in the book that
currently has NO hyperlink on it -- across the TOC, body, and Index,
using every pattern this pipeline knows how to recognize (p./pp. style,
bare Index-style numbers, and line-wrapped ranges).

For each one, classifies why it's likely unlinked:
  - "out of range"      -- the number isn't a valid page in this book
  - "GURPS title nearby" -- looks like a deliberate cross-book reference
  - "unexplained"        -- in-range, no obvious other-book title nearby;
                            worth a manual look, this is probably a gap
"""

import re
import pymupdf as fitz  # PyMuPDF -- `import fitz` is the deprecated alias
import xlsxwriter

SRC = "/mnt/user-data/outputs/GURPS_final_index_linked.pdf"
OUT_XLSX = "/mnt/user-data/outputs/GURPS_unlinked_references.xlsx"

BODY_START_IDX = 10
BODY_END_IDX = 593
TOC_IDXS = set(range(4, 10))
INDEX_IDXS = set(range(588, 594))
NBSP = "\u202f"

PP_SINGLE = re.compile(r'^\(?(pp?)\.[\s\u00a0' + NBSP + r']?(\d{1,4})(?:[\u2013\u2014-](\d{1,4}))?')
BARE_NUM = re.compile(r'^(\d{1,4})(?:[\u2013\u2014-](\d{1,4}))?[.,;)]*$')
WRAP_START = re.compile(r'^(\d{1,4})[\u2013\u2014-]$')
WRAP_CONT = re.compile(r'^(\d{1,4})')
TITLE_CONNECTORS = {"and", "of", "the", "in", "for", "to", "a", "an", "or", "&"}
LOOKBACK_WORDS = 10


def printed_to_index(n):
    idx = n + 9
    if BODY_START_IDX <= idx <= BODY_END_IDX:
        return idx
    return None


def printed_label(idx_1based):
    romans = ['', 'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii']
    if idx_1based <= 10:
        if 2 <= idx_1based - 1 < len(romans) + 1:
            return romans[idx_1based - 2]
        return 'front'
    return str(idx_1based - 10)


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


def gurps_title_nearby(words, ref_idx):
    lo = max(0, ref_idx - LOOKBACK_WORDS)
    span = words[lo:ref_idx]
    for start in range(len(span)):
        bare_tok = span[start][4].strip("(),;:").lower()
        if bare_tok == "gurps":
            between = span[start + 1:]
            if looks_like_title_span([w[4] for w in between]):
                return " ".join(w[4] for w in span[start:])
    return None


def context_snippet(words, i, j, pad=6):
    lo = max(0, i - pad)
    hi = min(len(words), j + 1 + pad)
    return " ".join(w[4] for w in words[lo:hi])


def find_candidates(page, is_index_page):
    """Return list of (word_start_idx, word_end_idx, rect, number, matched_text)."""
    words = page.get_text("words")
    h = page.rect.height
    candidates = []
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
            candidates.append((j, j, num, tok))
            consumed.add(j)
            j += 1
            continue
        if tok.lower() in ("p.", "pp.", "(p.", "(pp.") and j + 1 < len(words):
            nxt = words[j + 1][4]
            nm = re.match(r"^(\d{1,4})", nxt)
            if nm:
                num = int(nm.group(1))
                candidates.append((j, j + 1, num, tok + " " + nxt))
                consumed.add(j)
                consumed.add(j + 1)
                j += 2
                continue
        j += 1

    if is_index_page:
        # wrapped ranges
        for i, w in enumerate(words):
            if i in consumed:
                continue
            m = WRAP_START.match(w[4])
            if not m or i + 1 >= len(words) or (i + 1) in consumed:
                continue
            nm = WRAP_CONT.match(words[i + 1][4])
            if not nm:
                continue
            num = int(m.group(1))
            candidates.append((i, i, num, w[4]))
            candidates.append((i + 1, i + 1, num, words[i + 1][4]))
            consumed.add(i)
            consumed.add(i + 1)

        # bare numbers
        for i, w in enumerate(words):
            if i in consumed:
                continue
            if w[3] > h - 45:
                continue
            m = BARE_NUM.match(w[4])
            if not m:
                continue
            num = int(m.group(1))
            candidates.append((i, i, num, w[4]))

    return candidates, words


def main():
    doc = fitz.open(SRC)
    rows = []

    for i in range(BODY_START_IDX, BODY_END_IDX + 1):
        page = doc[i]
        existing_links = [l["from"] for l in page.get_links()]
        is_idx_page = i in INDEX_IDXS

        candidates, words = find_candidates(page, is_idx_page)
        for wi, wj, num, text in candidates:
            rect = fitz.Rect(words[wi][0], words[wi][1], words[wj][2], words[wj][3])
            already_linked = any(rect.intersects(r) for r in existing_links)
            if already_linked:
                continue

            target = printed_to_index(num)
            reason = "unexplained -- possible gap"
            if target is None:
                reason = "out of range"
            else:
                title = gurps_title_nearby(words, wi)
                if title:
                    reason = f"GURPS title nearby: {title!r}"

            snippet = context_snippet(words, wi, wj)
            rows.append((
                printed_label(i + 1), i + 1, "Index" if is_idx_page else "Body",
                text, num, reason, snippet
            ))

    wb = xlsxwriter.Workbook(OUT_XLSX)
    ws = wb.add_worksheet("Unlinked References")
    ws.write_row(0, 0, ["Page Label", "PDF Page", "Section", "Matched Text",
                         "Ref Number", "Likely Reason", "Context"])
    for r, row in enumerate(rows, start=1):
        ws.write_row(r, 0, list(row))

    unexplained = [r for r in rows if r[5] == "unexplained -- possible gap"]
    ws2 = wb.add_worksheet("Unexplained (priority)")
    ws2.write_row(0, 0, ["Page Label", "PDF Page", "Section", "Matched Text",
                          "Ref Number", "Context"])
    for r, row in enumerate(unexplained, start=1):
        ws2.write_row(r, 0, [row[0], row[1], row[2], row[3], row[4], row[6]])

    ws3 = wb.add_worksheet("Summary")
    from collections import Counter
    reason_counts = Counter(r[5].split(":")[0] for r in rows)
    ws3.write_row(0, 0, ["Reason", "Count"])
    for r, (reason, count) in enumerate(reason_counts.items(), start=1):
        ws3.write_row(r, 0, [reason, count])
    ws3.write_row(len(reason_counts) + 2, 0, ["TOTAL unlinked references found", len(rows)])

    wb.close()

    print(f"Total unlinked reference-looking text found: {len(rows)}")
    for reason, count in reason_counts.items():
        print(f"  {reason}: {count}")
    print(f"\nWrote {OUT_XLSX}")


if __name__ == "__main__":
    main()
