#!/usr/bin/env python3
"""
extract_gurps_wraparound_cover.py

Many RPG/publisher PDFs store the full wraparound cover art (back cover +
spine + front cover) on one page, but define a CropBox smaller than the
MediaBox so ordinary viewers only ever show the front-cover slice. Book
server thumbnailers (e.g. BookOrbit) sometimes ignore the CropBox and
render the whole MediaBox, which is how the full art becomes visible.

This script:
  1. Finds the wraparound cover page in a PDF (auto-detected by comparing
     each page's MediaBox area to its CropBox area, or given explicitly).
  2. Extracts that single page into its own PDF with the CropBox expanded
     to match the MediaBox, preserving all original vector/text objects
     and embedded images untouched.
  3. Converts that page to an SVG with all text outlined to paths, so the
     SVG has zero font dependencies (safe to open/print/share anywhere).

Requires: PyMuPDF  (pip install pymupdf --break-system-packages)

Usage:
    python3 extract_gurps_wraparound_cover.py INPUT.pdf [-o OUTPUT_PREFIX] [-p PAGE_NUM]

    INPUT.pdf         Path to the source PDF.
    -o, --output      Output filename prefix (default: derived from input
                       filename). Produces PREFIX.pdf and PREFIX.svg.
    -p, --page        1-based page number to extract, if you already know
                       it. Skips auto-detection.
    --list            List candidate cover pages (MediaBox vs CropBox for
                       every page) and exit without extracting anything.

Examples:
    python3 extract_gurps_wraparound_cover.py MyBook.pdf
    python3 extract_gurps_wraparound_cover.py MyBook.pdf -o outputs/MyBook_cover
    python3 extract_gurps_wraparound_cover.py MyBook.pdf -p 1
    python3 extract_gurps_wraparound_cover.py MyBook.pdf --list
"""

import argparse
import sys
from pathlib import Path

try:
    import pymupdf as fitz  # PyMuPDF (the "fitz" import name is deprecated)
except ImportError:
    sys.exit(
        "PyMuPDF is required but not installed.\n"
        "Install it with: pip install pymupdf --break-system-packages"
    )


def mediabox_area(page):
    r = page.mediabox
    return r.width * r.height


def cropbox_area(page):
    r = page.cropbox
    return r.width * r.height


def find_all_candidates(doc, min_ratio=1.15):
    """All (index, ratio) pairs whose MediaBox is meaningfully larger than
    its CropBox, in page order. min_ratio is the minimum
    (mediabox_area / cropbox_area) to count as a match."""
    candidates = []
    for i, page in enumerate(doc):
        ma, ca = mediabox_area(page), cropbox_area(page)
        if ca <= 0:
            continue
        ratio = ma / ca
        if ratio >= min_ratio:
            candidates.append((i, ratio))
    return candidates


def find_wraparound_page(doc, min_ratio=1.15):
    """
    Return the 0-based index of the highest-ratio page whose MediaBox is
    meaningfully larger than its CropBox (a strong signal that extra
    wraparound art is hiding outside the visible crop), or None if no
    page qualifies. Ties keep whichever page was found first.
    """
    candidates = find_all_candidates(doc, min_ratio)
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[1])[0]


def rects_overlap_area(a, b):
    ix0, iy0 = max(a.x0, b.x0), max(a.y0, b.y0)
    ix1, iy1 = min(a.x1, b.x1), min(a.y1, b.y1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return (ix1 - ix0) * (iy1 - iy0)


def find_complementary_page(doc, selected_index, selected_crop, candidates):
    """Among other candidate pages (same min_ratio threshold as the
    selected one), find one whose own original CropBox barely overlaps
    the selected page's own ORIGINAL CropBox -- a strong signal it holds
    the OTHER half of a spread that's split across two pages instead of
    duplicated on both (see revealed_region_blank_fraction()'s
    docstring). Returns the 0-based index, or None if no such page is
    found.

    selected_crop must be the selected page's CropBox as it was BEFORE
    extract_and_convert() expanded it out to the full MediaBox -- reading
    doc[selected_index].cropbox here instead would see that already-
    expanded box, which overlaps everything, and this would never find a
    complement."""
    selected_area = selected_crop.width * selected_crop.height
    for idx, _ratio in candidates:
        if idx == selected_index:
            continue
        other_crop = doc[idx].cropbox
        other_area = cropbox_area(doc[idx])
        overlap = rects_overlap_area(selected_crop, other_crop)
        if overlap < 0.1 * min(selected_area, other_area):
            return idx
    return None


def merge_split_pages(doc, idx_a, idx_b):
    """Build a new single-page document combining two pages that each
    independently hold only half of a wraparound spread instead of
    duplicating the full spread on both (confirmed real-world case: GURPS
    Basic Set, Fourth Edition Revised splits front and back cover across
    two pages, each with the other half of its own MediaBox left blank).

    This is a vector-level copy via show_pdf_page(), not a rasterized
    blend -- text stays live text, images stay embedded at their
    original resolution, nothing is re-rendered. Each source page's own
    CropBox is temporarily widened halfway across the gap between them
    (the two CropBoxes don't touch -- there's a spine-width no-man's-land
    neither page's own crop covers at all) so the merged result has no
    seam or blank strip where the two halves meet."""
    page_a, page_b = doc[idx_a], doc[idx_b]
    mediabox = page_a.mediabox
    crop_a, crop_b = page_a.cropbox, page_b.cropbox

    if crop_a.x0 >= crop_b.x1:
        left, right = idx_b, idx_a
        crop_left, crop_right = crop_b, crop_a
    elif crop_b.x0 >= crop_a.x1:
        left, right = idx_a, idx_b
        crop_left, crop_right = crop_a, crop_b
    else:
        return None  # not a clean left/right split -- don't guess

    gap_mid = (crop_left.x1 + crop_right.x0) / 2
    widened_left = fitz.Rect(mediabox.x0, mediabox.y0, gap_mid, mediabox.y1)
    widened_right = fitz.Rect(gap_mid, mediabox.y0, mediabox.x1, mediabox.y1)

    doc[left].set_cropbox(widened_left)
    doc[right].set_cropbox(widened_right)

    ox, oy = mediabox.x0, mediabox.y0

    def shift_rect(r):
        return fitz.Rect(r.x0 - ox, r.y0 - oy, r.x1 - ox, r.y1 - oy)

    merged_doc = fitz.open()
    new_page = merged_doc.new_page(width=mediabox.width, height=mediabox.height)
    new_page.show_pdf_page(shift_rect(widened_left), doc, left, keep_proportion=False)
    new_page.show_pdf_page(shift_rect(widened_right), doc, right, keep_proportion=False)
    return merged_doc


def revealed_region_blank_fraction(page, mediabox, orig_cropbox, dpi=30):
    """Fraction of the region revealed by expanding orig_cropbox out to
    mediabox that's a single dominant color -- a proxy for 'blank'.

    Some publisher PDFs split the wraparound spread across TWO pages
    instead of one -- confirmed on a real book (GURPS Basic Set, Fourth
    Edition Revised): page 1 has the front cover with the entire
    back-cover/spine half rendered blank, and page 2 has the back cover
    with the entire front-cover half rendered blank. Both pages still
    have the same oversized MediaBox-vs-CropBox ratio as a normal
    single-page wraparound cover, so find_wraparound_page() picks one of
    them same as always and silently produces an extraction that's only
    half-complete -- no error, just a large blank void where the rest of
    the art should be. This function gives extract_and_convert() a way to
    detect that and warn instead of staying silent."""
    mb, cb = mediabox, orig_cropbox
    if cb.x0 > mb.x0 + 1:
        revealed = fitz.Rect(mb.x0, mb.y0, cb.x0, mb.y1)
    elif cb.x1 < mb.x1 - 1:
        revealed = fitz.Rect(cb.x1, mb.y0, mb.x1, mb.y1)
    else:
        return 0.0  # cropbox already spans the full width -- nothing revealed
    clip_pix = page.get_pixmap(dpi=dpi, clip=revealed)
    samples = clip_pix.samples
    n = clip_pix.n
    from collections import Counter
    pixels = [samples[i:i + n] for i in range(0, len(samples), n)]
    if not pixels:
        return 0.0
    return Counter(pixels).most_common(1)[0][1] / len(pixels)


def list_candidates(doc):
    print(f"{'Page':>5}  {'MediaBox (w x h)':>22}  {'CropBox (w x h)':>22}  {'Ratio':>7}")
    for i, page in enumerate(doc):
        mb, cb = page.mediabox, page.cropbox
        ratio = mediabox_area(page) / cropbox_area(page) if cropbox_area(page) else float("inf")
        flag = "  <-- likely wraparound cover" if ratio >= 1.15 else ""
        print(
            f"{i + 1:>5}  {mb.width:>9.1f} x {mb.height:<9.1f}  "
            f"{cb.width:>9.1f} x {cb.height:<9.1f}  {ratio:>6.2f}x{flag}"
        )


def extract_and_convert(src_path, page_index, output_prefix, min_ratio=1.15, blank_threshold=0.90):
    doc = fitz.open(src_path)

    if page_index < 0 or page_index >= doc.page_count:
        sys.exit(f"Page {page_index + 1} is out of range (PDF has {doc.page_count} pages).")

    probe = doc[page_index]
    mediabox, orig_cropbox = probe.mediabox, probe.cropbox
    probe.set_cropbox(mediabox)
    blank_fraction = revealed_region_blank_fraction(probe, mediabox, orig_cropbox)
    probe.set_cropbox(orig_cropbox)  # restore -- merge_split_pages() needs the real crop

    merged_with = None
    incomplete_warning = False
    merged_doc = None

    if blank_fraction >= blank_threshold:
        # This page's own MediaBox probably doesn't hold the complete
        # spread -- see merge_split_pages()'s docstring. Look for the
        # other half before giving up and just warning. Must happen
        # before doc.select() below, while doc still has every page.
        candidates = find_all_candidates(doc, min_ratio)
        complement_idx = find_complementary_page(doc, page_index, orig_cropbox, candidates)
        if complement_idx is not None:
            merged_doc = merge_split_pages(doc, page_index, complement_idx)
            if merged_doc is not None:
                merged_with = complement_idx
        if merged_doc is None:
            incomplete_warning = True

    if merged_doc is not None:
        out_doc, out_page = merged_doc, merged_doc[0]
    else:
        # Step 1: pull out just that page, expand CropBox to the full MediaBox.
        doc.select([page_index])
        out_page = doc[0]
        out_page.set_cropbox(out_page.mediabox)
        out_doc = doc

    pdf_out = f"{output_prefix}.pdf"
    out_doc.save(pdf_out, garbage=3, deflate=True)

    # Step 2: convert to SVG with all text outlined to paths (no font deps).
    svg_out = f"{output_prefix}.svg"
    svg_data = out_page.get_svg_image(matrix=fitz.Identity, text_as_path=True)
    with open(svg_out, "w") as f:
        f.write(svg_data)

    fonts = [f[3] for f in out_page.get_fonts()]
    if merged_doc is not None:
        merged_doc.close()
    doc.close()

    return pdf_out, svg_out, fonts, incomplete_warning, merged_with


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="Source PDF file")
    parser.add_argument("-o", "--output", help="Output filename prefix (default: derived from input name)")
    parser.add_argument("-p", "--page", type=int, help="1-based page number to extract (skips auto-detection)")
    parser.add_argument("--list", action="store_true", help="List MediaBox/CropBox for every page and exit")
    parser.add_argument(
        "--min-ratio",
        type=float,
        default=1.15,
        help="Minimum MediaBox/CropBox area ratio to auto-detect a wraparound page (default: 1.15)",
    )
    args = parser.parse_args()

    src_path = Path(args.input)
    if not src_path.exists():
        sys.exit(f"File not found: {src_path}")

    doc = fitz.open(str(src_path))

    if args.list:
        list_candidates(doc)
        return

    if args.page is not None:
        page_index = args.page - 1
    else:
        page_index = find_wraparound_page(doc, min_ratio=args.min_ratio)
        if page_index is None:
            doc.close()
            sys.exit(
                "Couldn't auto-detect a wraparound cover page (no page's MediaBox was "
                f"notably larger than its CropBox, threshold {args.min_ratio}x).\n"
                "Run with --list to inspect all pages, then pass -p PAGE_NUM explicitly."
            )
        print(f"Auto-detected wraparound cover on page {page_index + 1}.")

    doc.close()

    output_prefix = args.output or str(src_path.with_suffix("")) + "_wraparound_cover"

    pdf_out, svg_out, fonts, incomplete_warning, merged_with = extract_and_convert(
        str(src_path), page_index, output_prefix, min_ratio=args.min_ratio)

    if merged_with is not None:
        print(
            f"Page {page_index + 1}'s own MediaBox only held half the spread "
            f"(the rest was blank) -- combined it with page {merged_with + 1}, "
            "which held the other half, to get the complete wraparound art."
        )

    print(f"Saved: {pdf_out}")
    print(f"Saved: {svg_out}  (fonts outlined to paths)")
    if fonts:
        print(f"Fonts outlined ({len(fonts)}): {', '.join(sorted(set(fonts)))}")
    else:
        print("No embedded fonts found on this page (art-only cover).")

    if incomplete_warning:
        print(
            "\nWarning: most of the revealed area on this page is a single solid "
            "color, which usually means the artwork is INCOMPLETE -- some "
            "publisher PDFs split a wraparound spread across two separate pages "
            "(confirmed on a real book: one page holds the front cover with the "
            "back-cover/spine half blank, another page holds the back cover with "
            "the front-cover half blank) rather than one page holding the whole "
            "spread. Tried to find and combine the other half automatically but "
            "couldn't -- run with --list to check for another page with a similar "
            "MediaBox/CropBox ratio and extract it too with -p to check by hand."
        )


if __name__ == "__main__":
    main()
