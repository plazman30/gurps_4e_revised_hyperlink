#!/usr/bin/env python3
"""
tag_borders_ocg.py

Wraps colored border content in Optional Content Groups (PDF "layers")
so it can be toggled on/off in any viewer that supports PDF layers
(Acrobat, PDF-XChange, etc.)

Three layers are produced:

1. "Page Border" (default ON) - the maroon/chapter-color frame and
   header/footer bar visible on almost every page. This is NOT a
   stroked rectangle - it's a single large gradient `sh` shading paint
   operator, clipped to (nearly) the full page, that washes the whole
   page in a gradient; the white content-area fill drawn on top of it
   masks the middle, leaving the gradient visible only at the margins.
   Detection: track the active clip region's bounding-box area through
   a simulated q/Q graphics-state stack, and flag any `sh` whose active
   clip covers a large fraction of the page.

2. "Box Borders" (default ON) - smaller picture-frame rectangles
   stroked (S) with a chapter accent CMYK color around callout/sidebar
   boxes. Detection: simulate the stroke color through q/Q, flag S/s
   painted with a chromatic (non-gray) color, and require the path have
   more than a simple 2-point line (so colored table/rule dividers are
   NOT swept in).

3. "Border Text (fallback)" (default OFF) - the page-footer chapter
   name/page number (and any similarly-placed header text) is drawn
   with NO color of its own - it just inherits whatever fill color was
   last set on the page, which happens to be the white used for the
   content-area background fill. That makes it unreadable if "Page
   Border" is switched off. Detection: simulate the current nonstroking
   fill color through q/Q (like the stroke-color simulation above) and
   flag text-showing operators (Tj/TJ) painted in a white/near-white
   fill while positioned in the top or bottom page margin. Each flagged
   span is left untouched in place, and a SECOND copy of it is appended
   right after, wrapped in the new layer, with all internal fill-color
   operators stripped and a single explicit black fill forced at the
   top - so turning this layer on draws readable black text directly
   on top of the (invisible-when-Page-Border-is-off) original.

Usage
-----
    # Test on a page range first (0-indexed, inclusive):
    python3 tag_borders_ocg.py input.pdf test_output.pdf --pages 10-40

    # Full document:
    python3 tag_borders_ocg.py input.pdf output.pdf

    # Dry run (report only, no file written):
    python3 tag_borders_ocg.py input.pdf output.pdf --dry-run
"""

import argparse

import pikepdf
from pikepdf import Name, Operator, Dictionary, Array


LAYERS = {
    "page": {"layer_name": "Page Border", "resource_name": "/OCPageBorder", "default_on": True},
    "box": {"layer_name": "Box Borders", "resource_name": "/OCBoxBorders", "default_on": True},
    "text": {"layer_name": "Border Text (fallback)", "resource_name": "/OCBorderText", "default_on": False},
}

STROKE_COLOR_OPS = {"K", "RG", "G"}       # stroking CMYK / RGB / Gray color setters
FILL_COLOR_OPS = {"k", "rg", "g"}         # nonstroking CMYK / RGB / Gray color setters
PATH_END_OPS = {"n", "f", "F", "f*", "S", "s", "B", "B*", "b", "b*"}
PATH_POINT_OPS = {"m", "l", "c", "v", "y"}  # path-construction ops (take last 2 operands as x,y)
PATH_SEGMENT_OPS = {"l", "c", "v", "y"}     # ops after the initial 'm'
STROKE_PAINT_OPS = {"S", "s"}
TEXT_SHOW_OPS = {"Tj", "TJ", "'", '"'}
FILL_STRIP_OPS = {"k", "g", "rg", "sc", "scn"}  # dropped from the black-text duplicate
# Nested marked-content tags (BDC/BMC/EMC) copied verbatim from the original
# reuse the original's /MCID, producing duplicate MCIDs on the page once
# copied. That confuses at least one tested viewer's optional-content
# tracking badly enough that a second "hidden" duplicate on the same page
# stops actually being hidden. The duplicate is a pure visual fallback, not
# structure content, so nested tags are dropped entirely rather than kept.
DUP_STRIP_OPS = FILL_STRIP_OPS | {"BDC", "BMC", "EMC"}

MIN_SEGMENTS_FOR_BOX_BORDER = 2
CLIP_AREA_RATIO_FOR_PAGE_BORDER = 0.4
MARGIN_POINTS = 50
# A text-show op painted in white/near-white while positioned within
# this many points of the top or bottom of the page is treated as
# header/footer text that inherited an invisible-on-white fill color.


def is_accent_cmyk(vals):
    c, m, y, k = (float(v) for v in vals)
    return max(c, m, y) > 0.04


def is_accent_rgb(vals):
    r, g, b = (float(v) for v in vals)
    return (max(r, g, b) - min(r, g, b)) > 0.05


def is_accent_gray(vals):
    return False


ACCENT_CHECK = {"K": is_accent_cmyk, "RG": is_accent_rgb, "G": is_accent_gray}


def is_white_cmyk(vals):
    c, m, y, k = (float(v) for v in vals)
    return max(c, m, y, k) < 0.05


def is_white_rgb(vals):
    return all(float(v) > 0.9 for v in vals)


def is_white_gray(vals):
    return float(vals[0]) > 0.9


WHITE_CHECK = {"k": is_white_cmyk, "rg": is_white_rgb, "g": is_white_gray}


def bbox_area(points):
    if not points:
        return 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def find_tagged_regions(instructions, page_area, page_height):
    """Returns (border_blocks, border_bare, text_blocks, text_bare).

    border_blocks: {start_idx: (end_idx, kind)} for 'page'/'box' q...Q spans.
    border_bare: {idx: kind} for standalone page/box paint ops.
    text_blocks: {start_idx: end_idx} for white-margin-text spans to duplicate.
    text_bare: [idx] for standalone white-margin text ops with no wrapping.
    """

    state_stack = []  # (stroke_accent, clip_area, fill_white) pushed on 'q'
    stroke_accent = False
    clip_area = page_area
    fill_white = False

    q_idx_stack = []
    border_q_kind = {}

    mc_idx_stack = []
    text_mc_start = set()
    bt_idx = None
    bt_flag = False
    last_tm_ty = None

    path_points = []
    pending_clip_area = None

    border_blocks = {}
    border_bare = {}
    text_blocks = {}
    text_bare = []

    for idx, instr in enumerate(instructions):
        op = str(instr.operator)
        operands = instr.operands

        if op == "q":
            state_stack.append((stroke_accent, clip_area, fill_white))
            q_idx_stack.append(idx)

        elif op == "Q":
            if q_idx_stack:
                start = q_idx_stack.pop()
                if start in border_q_kind:
                    border_blocks[start] = (idx, border_q_kind.pop(start))
            if state_stack:
                stroke_accent, clip_area, fill_white = state_stack.pop()

        elif op in STROKE_COLOR_OPS:
            stroke_accent = ACCENT_CHECK[op](operands)

        elif op in FILL_COLOR_OPS:
            fill_white = WHITE_CHECK[op](operands)

        elif op == "re":
            x, y, w, h = (float(v) for v in operands)
            path_points.extend([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])

        elif op in PATH_POINT_OPS:
            x, y = (float(v) for v in operands[-2:])
            path_points.append((x, y))

        elif op in ("W", "W*"):
            pending_clip_area = bbox_area(path_points) if path_points else clip_area

        elif op in PATH_END_OPS:
            if op in STROKE_PAINT_OPS and stroke_accent:
                scan_start = q_idx_stack[-1] if q_idx_stack else max(0, idx - 20)
                segment = instructions[scan_start:idx]
                seg_count = sum(1 for si in segment if str(si.operator) in PATH_SEGMENT_OPS)
                is_box_shape = seg_count >= MIN_SEGMENTS_FOR_BOX_BORDER or any(
                    str(si.operator) == "h" for si in segment
                )
                if is_box_shape:
                    if q_idx_stack:
                        border_q_kind[q_idx_stack[-1]] = "box"
                    else:
                        border_bare[idx] = "box"

            if pending_clip_area is not None:
                clip_area = pending_clip_area
                pending_clip_area = None
            path_points = []

        elif op == "sh":
            if page_area > 0 and clip_area / page_area >= CLIP_AREA_RATIO_FOR_PAGE_BORDER:
                if q_idx_stack:
                    border_q_kind[q_idx_stack[-1]] = "page"
                else:
                    border_bare[idx] = "page"

        elif op == "BT":
            bt_idx = idx
            bt_flag = False
            last_tm_ty = None

        elif op == "ET":
            if bt_flag and bt_idx is not None:
                text_blocks[bt_idx] = idx
            bt_idx = None
            bt_flag = False

        elif op in ("BDC", "BMC"):
            mc_idx_stack.append(idx)

        elif op == "EMC":
            if mc_idx_stack:
                start = mc_idx_stack.pop()
                if start in text_mc_start:
                    text_blocks[start] = idx
                    text_mc_start.discard(start)

        elif op == "Tm":
            last_tm_ty = float(operands[5])

        elif op in TEXT_SHOW_OPS:
            if (
                fill_white
                and last_tm_ty is not None
                and (last_tm_ty < MARGIN_POINTS or last_tm_ty > page_height - MARGIN_POINTS)
            ):
                if mc_idx_stack:
                    text_mc_start.add(mc_idx_stack[0])
                elif bt_idx is not None:
                    bt_flag = True
                else:
                    text_bare.append(idx)

    return border_blocks, border_bare, text_blocks, text_bare


def make_bdc(resource_name):
    return pikepdf.ContentStreamInstruction(
        pikepdf._core._ObjectList([Name("/OC"), Name(resource_name)]),
        Operator("BDC"),
    )


EMC = pikepdf.ContentStreamInstruction(pikepdf._core._ObjectList([]), Operator("EMC"))
Q_OP = pikepdf.ContentStreamInstruction(pikepdf._core._ObjectList([]), Operator("Q"))
ET_OP = pikepdf.ContentStreamInstruction(pikepdf._core._ObjectList([]), Operator("ET"))
PUSH_STATE = pikepdf.ContentStreamInstruction(pikepdf._core._ObjectList([]), Operator("q"))
BLACK_FILL = pikepdf.ContentStreamInstruction([0, 0, 0, 1], Operator("k"))


def rebalanced_copy(span):
    """Return a copy of span's instructions - minus fill-color ops and
    minus nested marked-content tags (BDC/BMC/EMC, which would otherwise
    reuse the original's /MCID and duplicate it on the page) - that is
    also self-contained regardless of what precedes or follows the
    original span in the document:

    - A q or BT opened INSIDE the span may have its matching Q/ET
      OUTSIDE it (marked-content spans aren't required to also be
      q/Q- or BT/ET-balanced) - such a dangling open gets a
      compensating Q/ET appended at the end.
    - Conversely a Q or ET INSIDE the span may close a q/BT that was
      opened OUTSIDE it, before the span started (e.g. a second
      footer span on the same page opening with the Q that belongs to
      a dangling q from an earlier span). Keeping such an orphan
      Q/ET would pop/close past our own wrapper's state, corrupting
      everything drawn afterward - it's dropped instead.

    Either direction of imbalance left uncorrected can, once this
    copy is spliced into the page as its own OC-wrapped block,
    corrupt the graphics state for unrelated content later in the
    same page (wrong clip, wrong CTM, wrong color)."""

    kept_raw = [si for si in span if str(si.operator) not in DUP_STRIP_OPS]

    kept = []
    q_depth = 0
    bt_depth = 0
    for si in kept_raw:
        op = str(si.operator)
        if op == "q":
            q_depth += 1
            kept.append(si)
        elif op == "Q":
            if q_depth > 0:
                q_depth -= 1
                kept.append(si)
            # else: orphan Q closing a q opened before this span - drop it
        elif op == "BT":
            bt_depth += 1
            kept.append(si)
        elif op == "ET":
            if bt_depth > 0:
                bt_depth -= 1
                kept.append(si)
            # else: orphan ET closing a BT opened before this span - drop it
        else:
            kept.append(si)

    if bt_depth > 0:
        kept.extend([ET_OP] * bt_depth)
    if q_depth > 0:
        kept.extend([Q_OP] * q_depth)

    return kept


def build_tagged_stream(instructions, border_blocks, border_bare, text_blocks, text_bare):
    bdc_for_kind = {kind: make_bdc(info["resource_name"]) for kind, info in LAYERS.items()}

    # index -> event. 'wrap': (end, kind). 'dup': end.
    events = {}
    for start, (end, kind) in border_blocks.items():
        events[start] = ("wrap", end, kind)
    for idx, kind in border_bare.items():
        events[idx] = ("wrap", idx, kind)
    for start, end in text_blocks.items():
        events[start] = ("dup", end, None)
    for idx in text_bare:
        events[idx] = ("dup", idx, None)

    new_instructions = []
    text_resource_names = []  # unique per-occurrence names used on this page, for 'text'
    dup_counter = 0
    i = 0
    n = len(instructions)
    while i < n:
        if i in events:
            kind_type, end, kind = events[i]
            span = instructions[i:end + 1]
            if kind_type == "wrap":
                new_instructions.append(bdc_for_kind[kind])
                new_instructions.extend(span)
                new_instructions.append(EMC)
            else:  # duplicate-as-black-text
                # A distinct /Properties resource name per on-page occurrence
                # (even though every one points at the same OCG object) -
                # reusing one name for two separate BDC...EMC spans on the
                # same page was observed to break at least one viewer's
                # optional-content hiding for the second occurrence.
                resource_name = f"{LAYERS['text']['resource_name']}{dup_counter}"
                dup_counter += 1
                text_resource_names.append(resource_name)
                new_instructions.extend(span)  # original, untouched
                new_instructions.append(make_bdc(resource_name))
                # q/Q around the color change + content: a color-setting
                # operator still executes even while marked content is
                # hidden (only painting is suppressed) - without this q/Q,
                # forcing black here would permanently overwrite the
                # ambient/inherited fill color for the rest of the page,
                # corrupting any later original content that also relies
                # on inherited color (exactly what a second same-page
                # duplicate's untouched sibling span would do).
                new_instructions.append(PUSH_STATE)
                new_instructions.append(BLACK_FILL)
                new_instructions.extend(rebalanced_copy(span))
                new_instructions.append(Q_OP)
                new_instructions.append(EMC)
            i = end + 1
        else:
            new_instructions.append(instructions[i])
            i += 1

    return new_instructions, text_resource_names


def ensure_ocgs(pdf):
    """Create (or reuse) the border OCGs and register them in
    /OCProperties, respecting each layer's default on/off state.
    Returns {kind: ocg_indirect_object}."""

    root = pdf.Root

    existing = {}
    if "/OCProperties" in root:
        for ocg in root.OCProperties.OCGs:
            existing[str(ocg.get("/Name", ""))] = ocg

    if "/OCProperties" not in root:
        root.OCProperties = Dictionary(
            OCGs=Array([]),
            D=Dictionary(ON=Array([]), OFF=Array([]), Order=Array([]), BaseState=Name.ON),
        )

    result = {}
    for kind, info in LAYERS.items():
        name = info["layer_name"]
        if name in existing:
            result[kind] = existing[name]
            continue
        ocg = pdf.make_indirect(Dictionary(Type=Name.OCG, Name=name))
        root.OCProperties.OCGs.append(ocg)
        if info["default_on"]:
            root.OCProperties.D.ON.append(ocg)
        else:
            root.OCProperties.D.OFF.append(ocg)
        if "/Order" in root.OCProperties.D:
            root.OCProperties.D.Order.append(ocg)
        result[kind] = ocg

    return result





def ensure_page_resources(page, ocgs, kinds_used, text_resource_names):
    resources = page.obj.Resources
    if "/Properties" not in resources:
        resources.Properties = Dictionary()
    for kind in kinds_used:
        if kind == "text":
            continue
        resources.Properties[LAYERS[kind]["resource_name"]] = ocgs[kind]
    for name in text_resource_names:
        resources.Properties[name] = ocgs["text"]


def parse_page_range(spec, num_pages):
    if spec is None:
        return range(num_pages)
    start, end = spec.split("-")
    start, end = int(start), int(end)
    return range(start, min(end, num_pages - 1) + 1)


def page_dims(page):
    mb = page.obj.MediaBox
    x0, y0, x1, y1 = (float(v) for v in mb)
    return abs((x1 - x0) * (y1 - y0)), abs(y1 - y0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_pdf")
    ap.add_argument("output_pdf")
    ap.add_argument("--pages", help="0-indexed inclusive range to process, e.g. 10-40 (default: whole document)")
    ap.add_argument("--dry-run", action="store_true", help="Report tagging stats without writing output")
    args = ap.parse_args()

    pdf = pikepdf.open(args.input_pdf)
    num_pages = len(pdf.pages)
    page_range = parse_page_range(args.pages, num_pages)

    ocgs = None if args.dry_run else ensure_ocgs(pdf)

    totals = {"page": 0, "box": 0, "text": 0}
    pages_touched = 0

    for i in page_range:
        page = pdf.pages[i]
        page.contents_coalesce()
        instructions = pikepdf.parse_content_stream(page)
        area, height = page_dims(page)

        border_blocks, border_bare, text_blocks, text_bare = find_tagged_regions(instructions, area, height)
        if not border_blocks and not border_bare and not text_blocks and not text_bare:
            continue

        pages_touched += 1
        kinds_used = set()
        counts = {"page": 0, "box": 0, "text": 0}
        for _s, (_e, kind) in border_blocks.items():
            counts[kind] += 1
            kinds_used.add(kind)
        for _i2, kind in border_bare.items():
            counts[kind] += 1
            kinds_used.add(kind)
        n_text = len(text_blocks) + len(text_bare)
        counts["text"] += n_text
        if n_text:
            kinds_used.add("text")
        for k in totals:
            totals[k] += counts[k]

        print(f"page {i}: page={counts['page']} box={counts['box']} text={counts['text']}")

        if args.dry_run:
            continue

        new_instructions, text_resource_names = build_tagged_stream(
            instructions, border_blocks, border_bare, text_blocks, text_bare
        )
        new_bytes = pikepdf.unparse_content_stream(new_instructions)
        page.obj.Contents.write(new_bytes)
        ensure_page_resources(page, ocgs, kinds_used, text_resource_names)

    print()
    print(f"Pages scanned: {len(list(page_range))}")
    print(f"Pages with tagged content: {pages_touched}")
    print(f"Total page-border ops: {totals['page']}")
    print(f"Total box-border blocks: {totals['box']}")
    print(f"Total footer/header text spans duplicated: {totals['text']}")

    if not args.dry_run:
        pdf.save(args.output_pdf)
        print(f"\nSaved: {args.output_pdf}")
        print('Layers: "Page Border" (on), "Box Borders" (on), "Border Text (fallback)" (off)')
    else:
        print("\nDry run — no file written.")


if __name__ == "__main__":
    main()
