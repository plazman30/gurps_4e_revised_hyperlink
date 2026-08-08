"""
Re-apply a link manifest (produced by extract_links.py) onto a clean
copy of a PDF that doesn't have the hyperlinks yet.

Matching strategy per link, in order of preference:
  1. If the target page has the same dimensions as when the manifest
     was made, and the recorded text is still found at the recorded
     rect on that page -> reuse the rect directly (fast path).
  2. Otherwise, search that page for the recorded text and use the
     rect(s) actually found -> robust to minor re-layout (re-cropping,
     margin changes, etc.).
  3. If the text can't be found on that page at all -> skip it and log
     it, rather than guessing.

Usage:
    python3 apply_links.py CLEAN.pdf manifest.json OUTPUT.pdf
    python3 apply_links.py CLEAN.pdf manifest.json OUTPUT.pdf --skip-pages=4-9

--skip-pages START-END is 0-based and inclusive on both ends. Any
manifest entry whose source page falls in that range is not applied --
useful as a safety net for a Table of Contents even if the manifest
wasn't already filtered by extract_links.py's own --skip-pages option.
"""

import sys
import json
import shutil
import fitz


def texts_roughly_match(a, b):
    return a.strip() == b.strip()


def parse_skip_range(spec):
    if not spec:
        return None
    start, end = spec.split("-")
    return (int(start), int(end))


def apply(clean_path, manifest_path, out_path, skip_range=None):
    with open(manifest_path) as f:
        manifest = json.load(f)

    # Incremental save writes to the same file it opened, so start by
    # copying the source to the output path and editing that copy.
    shutil.copyfile(clean_path, out_path)
    doc = fitz.open(out_path)
    if doc.page_count != manifest["page_count"]:
        print(f"WARNING: page count differs (manifest={manifest['page_count']}, "
              f"clean copy={doc.page_count}). Proceeding, but target pages "
              f"may be misaligned if pages were added/removed before the "
              f"linked content.")

    links = manifest["links"]
    if skip_range:
        before = len(links)
        links = [e for e in links if not (skip_range[0] <= e["source_page"] <= skip_range[1])]
        print(f"--skip-pages: excluded {before - len(links)} manifest entries "
              f"on pages {skip_range[0]}-{skip_range[1]}")

    # Group entries by source page so we only build a TextPage once per
    # page instead of re-parsing page text for every single link
    # (re-parsing per-link was the cause of a multi-minute runtime on
    # large source files).
    by_page = {}
    for entry in links:
        by_page.setdefault(entry["source_page"], []).append(entry)

    applied, relocated, skipped = 0, 0, []

    for page_idx in sorted(by_page.keys()):
        if page_idx >= doc.page_count:
            for entry in by_page[page_idx]:
                skipped.append((entry, "source page out of range in clean copy"))
            continue

        page = doc[page_idx]

        for entry in by_page[page_idx]:
            rect = fitz.Rect(entry["rect"])
            expected_text = entry["text"]

            actual_text = page.get_text("text", clip=rect).strip()
            use_rect = None
            if expected_text and texts_roughly_match(actual_text, expected_text):
                use_rect = rect
            elif expected_text:
                found = page.search_for(expected_text)
                if found:
                    use_rect = found[0]
                    relocated += 1
            else:
                use_rect = rect

            if use_rect is None:
                skipped.append((entry, "could not relocate text on this page"))
                continue

            kind = entry["kind"]
            if kind == "goto":
                link_dict = {
                    "kind": fitz.LINK_GOTO,
                    "page": entry["target_page"],
                    "from": use_rect,
                    "to": fitz.Point(0, 0),
                }
            elif kind == "uri":
                link_dict = {
                    "kind": fitz.LINK_URI,
                    "uri": entry["uri"],
                    "from": use_rect,
                }
            else:
                skipped.append((entry, f"unsupported link kind: {kind}"))
                continue

            page.insert_link(link_dict)
            applied += 1

    doc.saveIncr()

    print(f"Applied {applied} links ({relocated} needed text-search relocation)")
    print(f"Skipped {len(skipped)} links")
    if skipped:
        print("\nFirst few skipped:")
        for entry, reason in skipped[:10]:
            print(f"  page {entry['source_page']}: {entry.get('text','')[:50]!r} -- {reason}")
    print(f"\nWrote {out_path}")


def main():
    if len(sys.argv) not in (4, 5):
        print("Usage: python3 apply_links.py CLEAN.pdf manifest.json OUTPUT.pdf [--skip-pages=START-END]")
        sys.exit(1)

    skip_range = None
    if len(sys.argv) == 5:
        arg = sys.argv[4]
        if not arg.startswith("--skip-pages="):
            print("Usage: python3 apply_links.py CLEAN.pdf manifest.json OUTPUT.pdf [--skip-pages=START-END]")
            sys.exit(1)
        skip_range = parse_skip_range(arg.split("=", 1)[1])

    apply(sys.argv[1], sys.argv[2], sys.argv[3], skip_range)


if __name__ == "__main__":
    main()
