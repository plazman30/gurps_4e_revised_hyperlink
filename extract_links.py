"""
Extract every link annotation from a PDF into a portable JSON manifest,
so verified-correct hyperlinks can be re-applied to a different copy of
the file later (e.g. after re-cropping, re-exporting, or other edits
that would otherwise wipe the annotations out).

For each link we save:
  - source page index
  - the link's rect (position on that page)
  - the exact text under that rect (for robust re-matching later, in
    case page layout shifts slightly between file versions)
  - what it points to: target page index (internal) or a URI (external)

Usage:
    python3 extract_links.py SOURCE.pdf manifest.json
    python3 extract_links.py SOURCE.pdf manifest.json --skip-pages 4-9

--skip-pages START-END is 0-based and inclusive on both ends, e.g. to
skip a Table of Contents that (per PyMuPDF's 0-based page indexing)
occupies pdf pages 5 through 10, use --skip-pages 4-9. Links whose
source page falls in that range are left out of the manifest entirely
-- useful when a book's TOC already has its own correct, native links
and you only want to carry over links you added elsewhere.
"""

import sys
import json
import fitz


def parse_skip_range(spec):
    if not spec:
        return None
    start, end = spec.split("-")
    return (int(start), int(end))


def extract(src_path, skip_range=None):
    doc = fitz.open(src_path)
    entries = []
    skipped_toc = 0
    for page_idx in range(doc.page_count):
        if skip_range and skip_range[0] <= page_idx <= skip_range[1]:
            skipped_toc += len(doc[page_idx].get_links())
            continue

        page = doc[page_idx]
        for link in page.get_links():
            rect = link.get("from")
            if rect is None:
                continue
            text = page.get_text("text", clip=rect).strip()
            if "\n" in text:
                # PyMuPDF's "text" mode clip extraction can pull in a
                # stray character from the line above (its internal word
                # bounding boxes are sometimes taller than the visible
                # glyph and bleed into neighboring lines). The real
                # reference text is reliably the last line; anything
                # before an embedded newline is that artifact.
                text = text.split("\n")[-1].strip()

            entry = {
                "source_page": page_idx,
                "rect": [rect.x0, rect.y0, rect.x1, rect.y1],
                "text": text,
            }

            target_page = link.get("page")
            if isinstance(target_page, str) and target_page.strip().isdigit():
                target_page = int(target_page.strip())
            if isinstance(target_page, int) and target_page >= 0:
                # Covers both plain GOTO links and named-destination links
                # (PyMuPDF resolves named destinations to a page number for
                # us already, so we don't need to preserve the original
                # /Names tree -- it wouldn't survive onto a different file
                # anyway).
                entry["kind"] = "goto"
                entry["target_page"] = target_page
            elif link.get("uri"):
                entry["kind"] = "uri"
                entry["uri"] = link.get("uri")
            else:
                entry["kind"] = "other"
                entry["raw"] = {k: v for k, v in link.items() if k != "from"}

            entries.append(entry)

    if skip_range and skipped_toc:
        print(f"Skipped {skipped_toc} links on pages {skip_range[0]}-{skip_range[1]} "
              f"(--skip-pages)")

    return entries


def main():
    if len(sys.argv) not in (3, 4):
        print("Usage: python3 extract_links.py SOURCE.pdf manifest.json [--skip-pages START-END]")
        sys.exit(1)

    src, out = sys.argv[1], sys.argv[2]
    skip_range = None
    if len(sys.argv) == 4:
        arg = sys.argv[3]
        if not arg.startswith("--skip-pages="):
            print("Usage: python3 extract_links.py SOURCE.pdf manifest.json [--skip-pages=START-END]")
            sys.exit(1)
        skip_range = parse_skip_range(arg.split("=", 1)[1])

    entries = extract(src, skip_range)

    with open(out, "w") as f:
        json.dump({
            "source_file": src,
            "page_count": fitz.open(src).page_count,
            "link_count": len(entries),
            "links": entries,
        }, f, indent=1)

    print(f"Extracted {len(entries)} links from {src} -> {out}")


if __name__ == "__main__":
    main()
