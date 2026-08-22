#!/usr/bin/env python3
"""
fix_page_labels.py -- Interactively rebuild a PDF's /PageLabels (the
printed page numbers a PDF viewer shows, independent of physical page
index) for the common scanned-book layout: an optional front cover,
some roman-numeral front matter, the arabic-numbered body, and an
optional back cover that can sit anywhere in the file (front matter,
the body, or the very end) rather than only ever being the last page.

USAGE:
    python3 fix_page_labels.py INPUT.pdf OUTPUT.pdf

Prompts for:
  1. Whether PDF page 1 is the front cover.
  2. Whether the back cover is the last page -- if not, what page it is
     (press Enter for "no back cover at all").
  3. What PDF page is actually printed page "1" (where arabic numbering
     starts).

Labeling rules:
  - The front cover (if any) and the back cover (if any) are both
    labeled the constant text "Cover" -- no page number.
  - Every page strictly between the front cover and printed page 1 gets
    sequential lowercase roman numerals (i, ii, iii, ...), skipping the
    back cover if it happens to fall in that range -- the roman count
    just continues through the pages on either side of it with no gap.
  - Every page from printed page 1 onward gets sequential arabic numbers
    (1, 2, 3, ...), again skipping the back cover if it falls in that
    range (including the common case where it's the very last page).

REQUIREMENTS:
    pip install pikepdf
"""

import sys
import shutil
import pikepdf


_ROMAN_NUMERALS = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]


def int_to_roman(num):
    result = []
    for value, symbol in _ROMAN_NUMERALS:
        while num >= value:
            result.append(symbol)
            num -= value
    return "".join(result)


def compute_label_ranges(page_count, is_cover, back_cover_idx, page1_idx):
    """Pure core logic, kept separate from the interactive prompting below
    so it can be unit-tested without simulating stdin. All page indices
    here are 0-based PDF indices, not printed page numbers.

    Returns a list of (start_idx, end_idx, kind, start_value) tuples,
    each a contiguous PHYSICAL page range sharing one PageLabels dict
    entry -- kind is 'cover' or 'roman' or 'arabic'; start_value is the
    printed number the range's first page should show (ignored for
    'cover', which has no visible number at all)."""
    cover_idx = 0 if is_cover else None
    excluded = {i for i in (cover_idx, back_cover_idx) if i is not None}

    per_page_kind = []
    roman_counter = 0
    arabic_counter = 0
    for idx in range(page_count):
        if idx in excluded:
            per_page_kind.append(("cover", None))
        elif idx < page1_idx:
            roman_counter += 1
            per_page_kind.append(("roman", roman_counter))
        else:
            arabic_counter += 1
            per_page_kind.append(("arabic", arabic_counter))

    ranges = []
    range_start = 0
    for i in range(1, page_count + 1):
        prev_kind, prev_val = per_page_kind[i - 1]
        cur = per_page_kind[i] if i < page_count else None
        same_run = (
            cur is not None
            and cur[0] == prev_kind
            and (prev_kind == "cover" or cur[1] == prev_val + 1)
        )
        if not same_run:
            start_kind, start_val = per_page_kind[range_start]
            ranges.append((range_start, i - 1, start_kind, start_val))
            range_start = i
    return ranges


def write_page_labels(pdf, ranges):
    nums = []
    for start_idx, end_idx, kind, start_value in ranges:
        d = pikepdf.Dictionary()
        if kind == "cover":
            d["/P"] = "Cover"
        elif kind == "roman":
            d["/S"] = pikepdf.Name("/r")
            d["/St"] = start_value
        elif kind == "arabic":
            d["/S"] = pikepdf.Name("/D")
            d["/St"] = start_value
        else:
            raise ValueError(f"Unknown label kind: {kind!r}")
        nums.append(start_idx)
        nums.append(d)
    pdf.Root.PageLabels = pdf.make_indirect(
        pikepdf.Dictionary(Nums=pikepdf.Array(nums))
    )


def render_label(kind, value):
    if kind == "cover":
        return "Cover"
    if kind == "roman":
        return int_to_roman(value).lower()
    return str(value)


def ask_yes_no(prompt):
    while True:
        ans = input(f"{prompt} (y/n): ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("Please answer y or n.")


def ask_int(prompt, low, high):
    while True:
        raw = input(prompt).strip()
        if not raw.isdigit():
            print("Please enter a page number.")
            continue
        n = int(raw)
        if not (low <= n <= high):
            print(f"Page number must be between {low} and {high}.")
            continue
        return n


def gather_inputs(page_count):
    is_cover = ask_yes_no("Is Page 1 the cover?")

    back_cover_idx = None
    if ask_yes_no("Is the back cover the last page in the book?"):
        back_cover_idx = page_count - 1
    else:
        raw = input(
            "What page is the back cover? (press Enter for no back cover): "
        ).strip()
        if raw:
            if not raw.isdigit() or not (1 <= int(raw) <= page_count):
                sys.exit(f"Error: {raw!r} is not a valid page number "
                         f"(1-{page_count}).")
            back_cover_idx = int(raw) - 1

    page1_page = ask_int(
        f"What page in the PDF is actually page 1? (1-{page_count}): ",
        1, page_count,
    )
    page1_idx = page1_page - 1

    if is_cover and page1_idx == 0:
        sys.exit("Error: page 1 can't be both the cover and printed page 1.")
    if back_cover_idx is not None and back_cover_idx == page1_idx:
        sys.exit("Error: the back cover page can't also be printed page 1.")
    if is_cover and back_cover_idx == 0:
        sys.exit("Error: the back cover can't be the same page as the front cover.")

    return is_cover, back_cover_idx, page1_idx


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 fix_page_labels.py INPUT.pdf OUTPUT.pdf")
        sys.exit(1)
    in_path, out_path = sys.argv[1], sys.argv[2]

    with pikepdf.open(in_path) as probe:
        page_count = len(probe.pages)
    print(f"{in_path}: {page_count} pages\n")

    is_cover, back_cover_idx, page1_idx = gather_inputs(page_count)
    ranges = compute_label_ranges(page_count, is_cover, back_cover_idx, page1_idx)

    shutil.copyfile(in_path, out_path)
    with pikepdf.open(out_path, allow_overwriting_input=True) as pdf:
        write_page_labels(pdf, ranges)
        pdf.save(out_path)

    print(f"\nWrote {out_path}. Resulting page labels:")
    with pikepdf.open(out_path) as check:
        for start_idx, end_idx, kind, start_value in ranges:
            first = render_label(kind, start_value)
            if end_idx == start_idx:
                print(f"  PDF page {start_idx + 1}: {first}")
            else:
                last_value = start_value + (end_idx - start_idx) if kind != "cover" else start_value
                last = render_label(kind, last_value)
                print(f"  PDF pages {start_idx + 1}-{end_idx + 1}: {first} .. {last}")


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nAborted.")
