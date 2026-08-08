"""
Remove existing links whose page reference is preceded by "GURPS"
immediately followed by what looks like another product's title (e.g.
"GURPS Powers, p. 40") -- these are references to a DIFFERENT book
that happens to share a page number with this one, and got linked to
the wrong (this book's own) page.

Deliberately conservative to avoid false positives:
  - Never touches the Table of Contents (its native links are already
    correct and this pattern shouldn't need to run there).
  - Requires "GURPS" within a short window of the reference AND every
    word in between to look like part of a title (capitalized, no
    sentence-ending punctuation) -- ordinary prose that merely mentions
    "GURPS" ("GURPS assumes you are... (p. 39)") won't match, since
    "assumes" is lowercase and breaks the title-shape requirement.

This is a cleanup pass over EXISTING links, not a new-link creator --
run it after any pipeline step that adds body/index links.
"""

import sys
import fitz

LOOKBACK_WORDS = 10     # max words to scan backward for "GURPS" (some titles are long, e.g. "GURPS Low-Tech Companion 2: Weapons and Warriors")
TOC_IDXS = set(range(4, 10))  # never touch the TOC
TITLE_CONNECTORS = {"and", "of", "the", "in", "for", "to", "a", "an", "or", "&"}


def find_word_index_for_rect(words, rect):
    for i, w in enumerate(words):
        wr = fitz.Rect(w[0], w[1], w[2], w[3])
        if wr.intersects(rect):
            return i
    return None


def looks_like_title_span(words):
    """True if this run of words looks like part of a product title
    (e.g. "Powers," or "Gun Fu") rather than ordinary sentence prose."""
    for w in words:
        bare = w.strip(",;:")
        if not bare:
            continue
        if bare.lower() in TITLE_CONNECTORS:
            continue
        if not (bare[0].isupper() or bare[0].isdigit()):
            return False
        if "." in bare[:-1]:  # a period not at the very end -> sentence break
            return False
    return True


def find_gurps_title_before(words, link_idx):
    """Look backward from the reference for a "GURPS <Title...>" run
    immediately (no unrelated words) preceding it. Returns the matched
    text if found, else None."""
    lo = max(0, link_idx - LOOKBACK_WORDS)
    span = words[lo:link_idx]
    for start in range(len(span)):
        bare_tok = span[start][4].strip("(),;:").lower()
        if bare_tok == "gurps":
            between = span[start + 1:]
            if looks_like_title_span([w[4] for w in between]):
                return " ".join(w[4] for w in span[start:])
    return None


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 remove_cross_book_links.py INPUT.pdf OUTPUT.pdf")
        sys.exit(1)

    src, out = sys.argv[1], sys.argv[2]
    doc = fitz.open(src)

    removed = []
    for i in range(doc.page_count):
        if i in TOC_IDXS:
            continue
        page = doc[i]
        words = page.get_text("words")
        links = page.get_links()

        to_remove = []
        for l in links:
            if not isinstance(l.get("page"), int):
                continue
            link_idx = find_word_index_for_rect(words, l["from"])
            if link_idx is None:
                continue
            match = find_gurps_title_before(words, link_idx)
            if match:
                to_remove.append((l, match))

        for l, match in to_remove:
            text = page.get_text("text", clip=l["from"]).strip()
            removed.append((i + 1, match, text))
            page.delete_link(l)

    doc.save(out, garbage=3, deflate=True)

    print(f"Removed {len(removed)} cross-book links:")
    for pdf_page, before, text in removed:
        print(f"  pdf page {pdf_page}: {before!r} + {text!r}")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
