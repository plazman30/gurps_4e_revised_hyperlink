#!/usr/bin/env python3
"""
Crop the WIDER of the left/right margins down to match the narrower one,
so left == right (text appears centered). Only the oversized margin is
trimmed -- nothing is padded, so pages shrink slightly. Odd and even
pages are handled separately (mirrored book layouts commonly have the
gutter on alternating sides), based on a sampled measurement across the
whole book. Pages whose size doesn't match the book's dominant page
size (e.g. cover art, fold-out spreads) are left untouched.

Preserves page-number labels, existing hyperlinks, and document
metadata (Title/Author/Subject/Keywords/Creator + XMP). Everything is
done with pikepdf, modifying the already-open document's page objects
directly rather than copying into a fresh writer -- the original
version of this script used pypdf's PdfWriter.append(), which turned
out to silently drop a small number of link annotations during the
copy step itself (independent of the cropping logic), plus dropped
/PageLabels and metadata the way pypdf writers do by default. Doing
everything in-place in one already-open pikepdf document sidesteps
both problems at the source instead of patching them after the fact.

USAGE:
    python3 crop_to_center.py INPUT.pdf OUTPUT.pdf

REQUIREMENTS:
    pip install pdfplumber pikepdf
"""

import sys
import statistics
from collections import Counter
import pdfplumber
import pikepdf

MIN_CHARS = 30
SAMPLE_STRIDE = 3  # sample every Nth page to keep memory use sane on large books


def content_bbox_from_page(page):
    xs0, xs1, tops, bottoms = [], [], [], []

    def collect(objs):
        for o in objs:
            xs0.append(o["x0"]); xs1.append(o["x1"])
            tops.append(o["top"]); bottoms.append(o["bottom"])

    collect(page.chars)
    collect(page.images)
    collect(page.rects)
    collect(page.lines)
    collect(page.curves)

    if not xs0:
        return None
    return min(xs0), max(xs1), min(tops), max(bottoms)


def measure_margins(src_path, n):
    size_counts = Counter()
    with pdfplumber.open(src_path) as pdf:
        for page in pdf.pages:
            size_counts[(round(page.width, 1), round(page.height, 1))] += 1
    body_size, _ = size_counts.most_common(1)[0]
    print(f"Dominant page size: {body_size} ({size_counts[body_size]}/{n} pages)")

    odd_left, odd_right, even_left, even_right = [], [], [], []
    with pdfplumber.open(src_path) as pdf:
        for i in range(0, n, SAMPLE_STRIDE):
            page = pdf.pages[i]
            size = (round(page.width, 1), round(page.height, 1))
            if size != body_size:
                page.flush_cache(); del page
                continue
            bbox = content_bbox_from_page(page)
            if bbox:
                x0, x1, top, bottom = bbox
                left = x0
                right = page.width - x1
                pnum = i + 1
                if pnum % 2 == 1:
                    odd_left.append(left); odd_right.append(right)
                else:
                    even_left.append(left); even_right.append(right)
            page.flush_cache()
            del page

    odd_l, odd_r = statistics.median(odd_left), statistics.median(odd_right)
    even_l, even_r = statistics.median(even_left), statistics.median(even_right)
    return body_size, odd_l, odd_r, even_l, even_r


def restore_metadata(pdf, src_path):
    """Copy Title/Author/Subject/Keywords/Creator/CreationDate + XMP from
    the original file. PageLabels and links need no restoring here --
    since we never left pikepdf's single open document, they were never
    lost in the first place."""
    orig = pikepdf.open(src_path)

    def s(key):
        v = orig.docinfo.get(key)
        return str(v) if v is not None else None

    for key in ("/Title", "/Author", "/Subject", "/Keywords", "/Creator", "/CreationDate"):
        val = s(key)
        if val is not None:
            pdf.docinfo[key] = pikepdf.String(val)
    pdf.docinfo["/Producer"] = pikepdf.String("pikepdf (cropped)")

    import datetime
    now = datetime.datetime.now().astimezone().strftime("D:%Y%m%d%H%M%S%z")
    now = now[:-2] + "'" + now[-2:] + "'"
    pdf.docinfo["/ModDate"] = pikepdf.String(now)

    with pdf.open_metadata() as meta:
        meta.load_from_docinfo(pdf.docinfo)


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 crop_to_center.py INPUT.pdf OUTPUT.pdf")
        sys.exit(1)

    src, out = sys.argv[1], sys.argv[2]

    pdf = pikepdf.open(src)
    n = len(pdf.pages)

    body_size, odd_l, odd_r, even_l, even_r = measure_margins(src, n)
    odd_target = min(odd_l, odd_r)
    even_target = min(even_l, even_r)

    print(f"Odd pages : left={odd_l:.2f} right={odd_r:.2f} -> both {odd_target:.2f} "
          f"(cropping {'left' if odd_l > odd_r else 'right'})")
    print(f"Even pages: left={even_l:.2f} right={even_r:.2f} -> both {even_target:.2f} "
          f"(cropping {'left' if even_l > even_r else 'right'})")

    links_before = sum(
        1 for p in pdf.pages for a in (p.get("/Annots") or [])
        if a.get("/Subtype") == pikepdf.Name("/Link")
    )

    cropped, skipped = 0, 0
    for i, page in enumerate(pdf.pages):
        mb = page.MediaBox
        width = round(float(mb[2]) - float(mb[0]), 1)
        height = round(float(mb[3]) - float(mb[1]), 1)
        if (width, height) != body_size:
            skipped += 1
            continue

        pnum = i + 1
        if pnum % 2 == 1:
            l, r, target = odd_l, odd_r, odd_target
        else:
            l, r, target = even_l, even_r, even_target

        left_pt = float(mb[0])
        right_pt = float(mb[2])
        if l > r:
            new_left = left_pt + (l - target)
            new_right = right_pt
        else:
            new_left = left_pt
            new_right = right_pt - (r - target)

        new_box = pikepdf.Array([new_left, mb[1], new_right, mb[3]])
        page.MediaBox = new_box
        page.CropBox = new_box
        cropped += 1

    print(f"\nCropped {cropped} pages, left {skipped} non-body-size pages untouched")

    restore_metadata(pdf, src)
    print("Restored: metadata (Title/Author/Subject/Keywords/Creator), XMP metadata")
    print("(PageLabels and links were never dropped -- no copy step was used)")

    pdf.save(out)

    check = pikepdf.open(out)
    links_after = sum(
        1 for p in check.pages for a in (p.get("/Annots") or [])
        if a.get("/Subtype") == pikepdf.Name("/Link")
    )
    print(f"\nLinks: {links_before} before crop, {links_after} after "
          f"({'OK, preserved' if links_after == links_before else 'MISMATCH -- check output'})")

    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
