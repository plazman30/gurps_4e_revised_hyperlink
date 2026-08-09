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
"""

import argparse

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


if __name__ == "__main__":
    main()
