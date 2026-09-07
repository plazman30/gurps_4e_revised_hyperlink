#!/usr/bin/env python3
"""
pdfsqueeze.py — PDF Squeezer-style compression for Linux.

Wraps qpdf (lossless structural cleanup) and Ghostscript (image
downsampling/recompression) to approximate PDF Squeezer's compression
profiles on Fedora/Linux.

Requires: qpdf, ghostscript (gs)
    dnf install qpdf ghostscript

Usage:
    pdfsqueeze.py FILE [FILE ...] [options]

Examples:
    # Light compression, replace originals in place
    pdfsqueeze.py *.pdf --profile light --replace

    # Heavy compression to a separate output folder
    pdfsqueeze.py scan1.pdf scan2.pdf --profile heavy --output ./compressed

    # Recurse through a folder of PDFs
    pdfsqueeze.py ./comics --subfolders --profile medium --replace
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pikepdf

# Profiles approximate PDF Squeezer's Light / Medium / Heavy presets.
# dpi: downsample color/gray images above this resolution
# threshold: only downsample images more than `threshold`x the target dpi
#            (higher threshold = lighter touch, leaves near-target images alone)
# jpeg_q: JPEG re-encode quality (1-100)
# mono_dpi: downsample threshold for monochrome (1-bit) images, e.g. B&W scans
PROFILES = {
    "light": {
        "dpi": 300,
        "threshold": 1.5,
        "jpeg_q": 90,
        "mono_dpi": 600,
    },
    "medium": {
        "dpi": 200,
        "threshold": 1.3,
        "jpeg_q": 80,
        "mono_dpi": 400,
    },
    "heavy": {
        "dpi": 120,
        "threshold": 1.1,
        "jpeg_q": 65,
        "mono_dpi": 300,
    },
}


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def run(cmd, verbose=False, tolerate_codes=()):
    """Run cmd, raising on failure. `tolerate_codes` lets a caller accept a
    specific nonzero exit code that a tool uses for "succeeded, but with
    warnings" rather than a real failure (e.g. qpdf's exit code 3) -- any
    other nonzero code still raises."""
    if verbose:
        print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and result.returncode not in tolerate_codes:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(str(c) for c in cmd)}\n"
            f"{result.stderr.strip()}"
        )
    if result.returncode != 0 and result.stderr.strip():
        # A tolerated nonzero exit still means the tool has something worth
        # showing (e.g. qpdf's own warning text) -- don't swallow it just
        # because it wasn't fatal.
        sys.stderr.write(f"  (warning) {result.stderr.strip()}\n")
    return result


def check_tools():
    missing = [t for t in ("qpdf", "gs") if shutil.which(t) is None]
    if missing:
        print(f"Missing required tool(s): {', '.join(missing)}", file=sys.stderr)
        print("Install with: sudo dnf install qpdf ghostscript", file=sys.stderr)
        sys.exit(1)


def qpdf_cleanup(src: Path, dst: Path, verbose=False):
    """Lossless structural cleanup: object streams, image optimization.

    qpdf exits 3 (not 0) when it fixes up a merely-imperfect input PDF
    (e.g. a reconstructed/incomplete stream) and still produces valid
    output -- confirmed on a real book, where qpdf's own message was
    "operation succeeded with warnings; resulting file may have some
    problems," and the resulting file had the identical page count, link
    count, and TOC as the source. Exit 3 is qpdf's documented
    warnings-only code (2 is reserved for a real error), so it's
    explicitly tolerated here rather than aborting the whole pipeline on
    an ordinary real-world PDF before Ghostscript even runs."""
    run(
        [
            "qpdf",
            "--object-streams=generate",
            "--compress-streams=y",
            "--recompress-flate",
            "--optimize-images",
            str(src),
            str(dst),
        ],
        verbose=verbose,
        tolerate_codes={3},
    )


def ghostscript_compress(src: Path, dst: Path, profile: dict, verbose=False):
    """Lossy image downsampling/recompression via Ghostscript."""
    run(
        [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            "-dNOPAUSE",
            "-dBATCH",
            "-dQUIET",
            "-dDetectDuplicateImages=true",
            "-dCompressFonts=true",
            "-dSubsetFonts=true",
            "-dDownsampleColorImages=true",
            f"-dColorImageResolution={profile['dpi']}",
            f"-dColorImageDownsampleThreshold={profile['threshold']}",
            "-dDownsampleGrayImages=true",
            f"-dGrayImageResolution={profile['dpi']}",
            f"-dGrayImageDownsampleThreshold={profile['threshold']}",
            "-dDownsampleMonoImages=true",
            f"-dMonoImageResolution={profile['mono_dpi']}",
            "-dAutoFilterColorImages=false",
            "-dColorImageFilter=/DCTEncode",
            "-dAutoFilterGrayImages=false",
            "-dGrayImageFilter=/DCTEncode",
            f"-dJPEGQ={profile['jpeg_q']}",
            f"-sOutputFile={dst}",
            str(src),
        ],
        verbose=verbose,
    )


def restore_metadata_and_labels(original: Path, converted: Path, final: Path) -> None:
    """Restore the original Info-dict + XMP metadata and /PageLabels onto
    the compressed output, using the same pikepdf pattern already
    established in this repo by convert_pdf_to_grayscale.py's function of
    the same name. Necessary because Ghostscript's pdfwrite device does
    not pass the original XMP packet through -- it regenerates one from
    scratch, carrying some fields over but not others, and confirmed on
    a real book to outright fabricate a `dc:title` of "Untitled" where
    none existed before in either XMP or the Info dict.

    Title/Author/Subject/Keywords and /PageLabels are confirmed restored
    correctly by this. /Producer, /CreationDate, and /ModDate are NOT,
    despite this function setting them correctly on the in-memory XMP
    object mid-call (confirmed directly) -- pikepdf's own
    `open_metadata(update_docinfo=True)` sync-on-close unconditionally
    re-stamps those same three fields with pikepdf's own current
    identity when the `with` block exits, on top of whatever this
    function just set, and a later direct `docinfo[...] = ...` write
    doesn't reliably survive `save()` either. This is a pikepdf-level
    behavior, independent of and in addition to Ghostscript's own
    identical habit -- so the net result matches, not diverges from,
    convert_pdf_to_grayscale.py's own documented limitation on these
    same three fields (its `--keep-producer` flag is a no-op for the
    same underlying reason, not a separate gap)."""
    with pikepdf.open(original) as src, pikepdf.open(converted) as out:
        with src.open_metadata() as src_meta, out.open_metadata() as out_meta:
            # clear() first: Ghostscript's pdfwrite device fabricates its
            # own XMP fields with no basis in the source (confirmed on a
            # real book: a dc:title of "Untitled" where neither the
            # source's XMP nor its Info dict had any title at all).
            # load_from_docinfo()/update() are both additive -- they
            # only ever set keys present in their argument, never delete
            # an existing key that argument doesn't mention -- so
            # without this, Ghostscript's fabricated fields would simply
            # survive underneath whatever this restores on top.
            out_meta.clear()
            out_meta.load_from_docinfo(src.docinfo)
            out_meta.update(src_meta)

        if "/PageLabels" in src.Root:
            labels = src.Root.PageLabels
            # copy_foreign() requires an indirect object; a /PageLabels
            # dict built as a *direct* object on /Root (confirmed to
            # happen -- pikepdf.new() plus a plain dict assignment
            # produces exactly this) raises ForeignObjectError otherwise.
            # make_indirect() is safe to call on src here since src is
            # only ever read from, never saved.
            if not labels.is_indirect:
                labels = src.make_indirect(labels)
            out.Root.PageLabels = out.copy_foreign(labels)

        out.save(final)


def compress_one(src: Path, dst: Path, profile: dict, verbose=False):
    with tempfile.TemporaryDirectory() as tmp:
        stage1 = Path(tmp) / "stage1.pdf"
        stage2 = Path(tmp) / "stage2.pdf"
        qpdf_cleanup(src, stage1, verbose=verbose)
        ghostscript_compress(stage1, stage2, profile, verbose=verbose)
        restore_metadata_and_labels(src, stage2, dst)


def _link_signature(link: dict) -> tuple:
    """A comparable fingerprint for a link, ignoring xref/id (which change).

    LINK_GOTO (kind 1) and LINK_NAMED (kind 4) are treated as equivalent,
    keyed on the resolved target page rather than the raw annotation
    kind. Confirmed on a real book: Ghostscript's pdfwrite device
    resolves an internal named-destination link (InDesign's usual export
    convention for cross-references, confirmed via the ".indd:" marker
    in its own `nameddest` string) into a direct page/point GoTo during
    recompression -- same rect, same effective target page, only the
    annotation's own on-disk encoding changes. That's a harmless
    re-encoding, not a broken or lost link, but comparing raw `kind`
    values flagged every single one as "missing" on a real 251-link test
    file (238 of them), even though the true link counts before and
    after were identical. (This also makes moot a related bug this
    replaced: the kind-4 branch used to read `link.get("name")`, but
    PyMuPDF actually stores a named destination's target string under
    `"nameddest"`, not `"name"` -- so that field was always `None`.)"""
    kind = link.get("kind")
    rect = link.get("from")
    rect_sig = tuple(round(v, 1) for v in rect) if rect else None
    if kind in (1, 4):  # LINK_GOTO / LINK_NAMED -- same effective navigation
        return ("goto", rect_sig, link.get("page"))
    if kind == 2:  # LINK_URI
        return (kind, rect_sig, link.get("uri"))
    if kind == 3:  # LINK_LAUNCH
        return (kind, rect_sig, link.get("file"))
    return (kind, rect_sig)


def verify_links(src: Path, dst: Path) -> list[str]:
    """
    Compare links, TOC/bookmarks, and page count between src and dst.
    Returns a list of human-readable problem descriptions (empty = all clear).
    """
    try:
        import pymupdf
    except ImportError:
        return [
            "pymupdf not installed — skipping link verification "
            "(pip install pymupdf --break-system-packages)"
        ]

    problems = []
    doc_a = pymupdf.open(src)
    doc_b = pymupdf.open(dst)

    if doc_a.page_count != doc_b.page_count:
        problems.append(
            f"page count changed: {doc_a.page_count} -> {doc_b.page_count}"
        )

    total_links_a = total_links_b = 0
    for i in range(min(doc_a.page_count, doc_b.page_count)):
        links_a = {_link_signature(l) for l in doc_a[i].get_links()}
        links_b = {_link_signature(l) for l in doc_b[i].get_links()}
        total_links_a += len(links_a)
        total_links_b += len(links_b)
        missing = links_a - links_b
        if missing:
            problems.append(f"page {i + 1}: {len(missing)} link(s) missing after compression")

    if total_links_a and total_links_a != total_links_b:
        problems.append(
            f"total link count changed: {total_links_a} -> {total_links_b}"
        )

    toc_a = doc_a.get_toc()
    toc_b = doc_b.get_toc()
    if toc_a != toc_b:
        if len(toc_a) != len(toc_b):
            problems.append(
                f"bookmarks/TOC entry count changed: {len(toc_a)} -> {len(toc_b)}"
            )
        else:
            problems.append("bookmarks/TOC entries changed (titles or targets differ)")

    doc_a.close()
    doc_b.close()
    return problems


def collect_inputs(paths, subfolders):
    """Returns a list of (path, rel_name) pairs. `rel_name` is the path
    relative to whichever directory argument it was found under (so
    `--subfolders` preserves subfolder structure in the output, the same
    way `hyperlink_pdf_universal.py --batch --recursive` already does in
    this repo) -- for a file passed directly on the command line, or
    found in a non-recursive folder listing, `rel_name` is just its
    plain filename."""
    files = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            pattern = "**/*.pdf" if subfolders else "*.pdf"
            for f in sorted(path.glob(pattern)):
                files.append((f, f.relative_to(path)))
        elif path.is_file():
            files.append((path, Path(path.name)))
        else:
            print(f"Warning: {p} not found, skipping", file=sys.stderr)
    return files


def resolve_output(
    src: Path, rel_name: Path, output_arg: str | None, replace: bool, multiple: bool
) -> Path:
    if output_arg:
        out_path = Path(output_arg)
        treat_as_dir = out_path.is_dir() or output_arg.endswith("/") or multiple
        if treat_as_dir:
            dst = out_path / rel_name
            dst.parent.mkdir(parents=True, exist_ok=True)
            return dst
        out_path.parent.mkdir(parents=True, exist_ok=True)
        return out_path
    if replace:
        return src
    # default: same folder, "-compressed" suffix
    return src.with_name(f"{src.stem}-compressed{src.suffix}")


def main():
    parser = argparse.ArgumentParser(
        description="PDF Squeezer-style compression for Linux (qpdf + Ghostscript).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("paths", nargs="+", help="PDF files or folders to compress")
    parser.add_argument(
        "--profile",
        choices=PROFILES.keys(),
        default="light",
        help="Compression strength (default: light)",
    )
    parser.add_argument(
        "--output", help="Output folder or file path (default: alongside input)"
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Overwrite the original file (original is not deleted unless --no-backup)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="With --replace, don't keep a .bak copy of the original",
    )
    parser.add_argument(
        "--subfolders", action="store_true", help="Recurse into subfolders"
    )
    parser.add_argument("--verbose", action="store_true", help="Show tool commands")
    parser.add_argument(
        "--verify-links",
        action="store_true",
        help="Check that hyperlinks, TOC/bookmarks, and page count survive "
        "compression (requires pymupdf); warns per-file if anything's missing",
    )
    args = parser.parse_args()

    check_tools()
    profile = PROFILES[args.profile]

    inputs = collect_inputs(args.paths, args.subfolders)
    if not inputs:
        print("No PDF files found.", file=sys.stderr)
        sys.exit(1)

    multiple = len(inputs) > 1
    for src, rel_name in inputs:
        dst = resolve_output(src, rel_name, args.output, args.replace, multiple)
        working_dst = dst.with_suffix(".tmp.pdf") if dst == src else dst

        try:
            orig_size = src.stat().st_size
            compress_one(src, working_dst, profile, verbose=args.verbose)
            new_size = working_dst.stat().st_size

            link_problems = (
                verify_links(src, working_dst) if args.verify_links else []
            )

            if dst == src:
                if not args.no_backup:
                    backup = src.with_suffix(src.suffix + ".bak")
                    shutil.copy2(src, backup)
                working_dst.replace(dst)

            pct = (1 - new_size / orig_size) * 100 if orig_size else 0
            print(
                f"{src.name}: {human_size(orig_size)} -> {human_size(new_size)} "
                f"({pct:+.1f}%) -> {dst}"
            )
            if link_problems:
                for problem in link_problems:
                    print(f"  WARNING: {problem}", file=sys.stderr)
            elif args.verify_links:
                print("  links/TOC/pages verified intact")
        except RuntimeError as e:
            print(f"Failed on {src}: {e}", file=sys.stderr)
            if working_dst.exists() and working_dst != dst:
                working_dst.unlink()


if __name__ == "__main__":
    main()
