#!/usr/bin/env python3
"""
pdf_grayscale.py — Convert a PDF to grayscale without losing hyperlinks,
metadata, or page labels.

Ghostscript's pdfwrite device converts color cleanly and preserves link
annotations, but it does NOT preserve document metadata (Info dict / XMP)
or /PageLabels — those get dropped during its full re-interpretation of
the input. This script runs Ghostscript for the color conversion, then
uses pikepdf to copy metadata and page labels back in from the original.

Usage:
    python3 pdf_grayscale.py input.pdf
    python3 pdf_grayscale.py input.pdf output.pdf
    python3 pdf_grayscale.py input.pdf output.pdf --keep-producer

With no output path given, it's derived from the input filename by
inserting "-grayscale" before the extension (e.g. "Book.pdf" ->
"Book-grayscale.pdf"), written alongside the input file.

Interactively asks whether the front/back cover pages should be converted
to grayscale too. Answering no keeps those specific pages exactly as they
are in the original (full color, untouched) while everything else is
converted.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import pikepdf


def run_ghostscript(src: Path, dst: Path) -> None:
    """Convert src to grayscale, writing to dst, preserving link annotations."""
    cmd = [
        "gs",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.6",
        "-sColorConversionStrategy=Gray",
        "-dProcessColorModel=/DeviceGray",
        "-dPreserveAnnots=true",
        "-dNOPAUSE",
        "-dBATCH",
        f"-sOutputFile={dst}",
        "-c", "/PreserveAnnotTypes [/Link] def",
        "-f", str(src),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"Ghostscript exited with code {result.returncode}")


def restore_metadata_and_labels(original: Path, converted: Path, final: Path,
                                 keep_producer: bool,
                                 keep_color_pages: "set[int]" = frozenset()) -> None:
    """Copy Info/XMP metadata and PageLabels from original onto converted,
    then swap back in any pages (0-indexed) that should stay in their
    original color instead of the grayscale-converted version."""
    with pikepdf.open(original) as src, pikepdf.open(converted) as out:
        # Restore XMP + DocInfo metadata
        with src.open_metadata() as src_meta, out.open_metadata() as out_meta:
            out_meta.load_from_docinfo(src.docinfo)
            out_meta.update(src_meta)
            if not keep_producer:
                # Let Ghostscript's Producer stand, showing the file was
                # regenerated — comment out this branch to fully spoof
                # the original Producer string instead.
                pass

        # Restore page labels (e.g. roman numerals for front matter)
        if "/PageLabels" in src.Root:
            out.Root.PageLabels = out.copy_foreign(src.Root.PageLabels)

        if keep_color_pages:
            if len(out.pages) != len(src.pages):
                raise RuntimeError(
                    "Page count changed during grayscale conversion "
                    f"({len(src.pages)} -> {len(out.pages)}) -- can't safely "
                    "map cover pages back by index."
                )
            for idx in keep_color_pages:
                out.pages[idx] = src.pages[idx]

        out.save(final)


def default_output_path(input_path: Path) -> Path:
    """input.pdf -> input-grayscale.pdf, alongside the input file."""
    return input_path.with_name(f"{input_path.stem}-grayscale{input_path.suffix}")


def prompt_yes_no(question: str, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        raw = input(f"{question} {suffix}: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print('Please answer "y" or "n".')


def prompt_page_number(question: str, default: int, total_pages: int,
                        allow_none: bool = False) -> "int | None":
    """Prompt for a 1-based page number, re-asking until it's either a
    valid page in range, blank (accepts the default), or (if allowed)
    the literal "none"."""
    while True:
        raw = input(f"{question} [{default}]: ").strip()
        if not raw:
            return default
        if allow_none and raw.lower() == "none":
            return None
        if raw.isdigit() and 1 <= int(raw) <= total_pages:
            return int(raw)
        none_hint = ', or "none"' if allow_none else ""
        print(f"Please enter a page number from 1 to {total_pages}{none_hint}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Source PDF")
    parser.add_argument(
        "output", type=Path, nargs="?",
        help="Destination grayscale PDF (default: <input>-grayscale.pdf)",
    )
    parser.add_argument(
        "--keep-producer", action="store_true",
        help="Reserved for future use; currently a no-op placeholder.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"Input file not found: {args.input}")

    output = args.output if args.output is not None else default_output_path(args.input)

    with pikepdf.open(args.input) as probe:
        total_pages = len(probe.pages)

    keep_color_pages: set[int] = set()
    if not prompt_yes_no("Convert the front and back cover to grayscale too?", default=True):
        front = prompt_page_number("Which page is the front cover?",
                                    default=1, total_pages=total_pages)
        back = prompt_page_number(
            'Which page is the back cover? Enter "none" if there is no back cover.',
            default=total_pages, total_pages=total_pages, allow_none=True)
        if front is not None:
            keep_color_pages.add(front - 1)
        if back is not None:
            keep_color_pages.add(back - 1)

    with tempfile.TemporaryDirectory() as tmp:
        gray_tmp = Path(tmp) / "gray.pdf"
        print(f"Converting to grayscale with Ghostscript...")
        run_ghostscript(args.input, gray_tmp)

        print("Restoring metadata and page labels with pikepdf...")
        restore_metadata_and_labels(args.input, gray_tmp, output,
                                     args.keep_producer, keep_color_pages)

    print(f"Done: {output}")


if __name__ == "__main__":
    main()
