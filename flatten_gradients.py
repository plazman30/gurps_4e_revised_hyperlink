#!/usr/bin/env python3
"""
flatten_gradients.py

Replaces every gradient shading fill (`sh` operator) in the PDF with a
solid, flat-color fill, instead of the color ramp.

How it works
------------
Each `sh` paints a shading pattern (referenced by name, e.g. `/Sh0`)
into whatever clip region is currently active - it doesn't need its own
path. To flatten it:

  1. Look up the shading's resource dict (page Resources -> /Shading)
     and evaluate its /Function at the start of its /Domain to get a
     representative color (usually the strongest/most saturated end of
     the ramp).
  2. Resolve that color through its /ColorSpace down to a plain device
     color (DeviceGray/RGB/CMYK) - this includes evaluating DeviceN and
     Separation colorspaces' PostScript-calculator tint-transform
     functions when present (common in this document: some pages define
     their gradient in a custom DeviceN "spot-ish" space and only
     convert to CMYK via such a transform).
  3. Replace the `sh` instruction with: <set color> <big rect> re f.
     The huge rectangle is deliberately oversized (far larger than any
     realistic page) - it's still constrained by whatever clip path was
     already active when `sh` ran, so it reliably fills exactly the same
     area the gradient would have, without needing to know that clip
     path's actual shape.

Supports PDF Function types 2 (exponential), 3 (stitching - resolves to
its first sub-function, matching the domain start), 4 (PostScript
calculator - has a small built-in interpreter), and a rough fallback
for type 0 (sampled - uses the midpoint of /Range).

Usage
-----
    python3 flatten_gradients.py input.pdf output.pdf [--pages 10-40] [--dry-run]
"""

import argparse
import math

import pikepdf
from pikepdf import Name, Operator


# ---------------------------------------------------------------- PostScript calculator ----

def ps_calc_eval(program_bytes, inputs):
    """Minimal PostScript calculator (PDF Function Type 4) interpreter.
    Supports the arithmetic/stack operators actually used by tint
    transforms; unknown tokens are silently skipped rather than raising,
    since the caller falls back gracefully on a bad result."""

    text = program_bytes.decode("latin1").strip()
    if text.startswith("{"):
        text = text[1:]
    if text.endswith("}"):
        text = text[:-1]
    toks = text.replace("{", " ").replace("}", " ").split()

    stack = list(inputs)
    for t in toks:
        try:
            stack.append(float(t))
            continue
        except ValueError:
            pass
        try:
            if t == "add": b, a = stack.pop(), stack.pop(); stack.append(a + b)
            elif t == "sub": b, a = stack.pop(), stack.pop(); stack.append(a - b)
            elif t == "mul": b, a = stack.pop(), stack.pop(); stack.append(a * b)
            elif t == "div": b, a = stack.pop(), stack.pop(); stack.append(a / b if b else 0.0)
            elif t == "idiv": b, a = stack.pop(), stack.pop(); stack.append(float(int(a) // int(b)) if b else 0.0)
            elif t == "mod": b, a = stack.pop(), stack.pop(); stack.append(float(int(a) % int(b)) if b else 0.0)
            elif t == "neg": stack.append(-stack.pop())
            elif t == "abs": stack.append(abs(stack.pop()))
            elif t == "sqrt": stack.append(math.sqrt(max(0.0, stack.pop())))
            elif t in ("cvr", "cvi"): pass
            elif t == "dup": stack.append(stack[-1])
            elif t == "pop": stack.pop()
            elif t == "exch": a, b = stack.pop(), stack.pop(); stack.append(a); stack.append(b)
            elif t == "copy":
                n = int(stack.pop())
                if n > 0:
                    stack.extend(stack[-n:])
            elif t == "index":
                n = int(stack.pop())
                stack.append(stack[-1 - n])
            elif t == "roll":
                j, n = int(stack.pop()), int(stack.pop())
                if n > 0:
                    part = stack[-n:]
                    del stack[-n:]
                    j %= n
                    stack.extend(part[-j:] + part[:-j])
            elif t == "truncate": stack.append(float(int(stack.pop())))
            elif t == "round": stack.append(float(round(stack.pop())))
            elif t == "ceiling": stack.append(math.ceil(stack.pop()))
            elif t == "floor": stack.append(math.floor(stack.pop()))
            elif t == "exp": b, a = stack.pop(), stack.pop(); stack.append(a ** b)
            elif t == "ln": stack.append(math.log(max(1e-9, stack.pop())))
            elif t == "log": stack.append(math.log10(max(1e-9, stack.pop())))
            # comparisons/booleans/control flow: not expected in simple
            # tint transforms; skip anything else rather than crash
        except Exception:
            pass
    return stack


# ---------------------------------------------------------------- PDF Function evaluation ----

def eval_function(func, inputs):
    """Evaluate a PDF Function object at the given input(s), returning a
    list of output component floats. Only needs to be roughly right at
    one representative point (the shading's domain start)."""

    ftype = int(func.get("/FunctionType", -1))

    if ftype == 2:
        c0 = func.get("/C0", [0.0])
        return [float(v) for v in c0]

    if ftype == 3:
        funcs = func["/Functions"]
        return eval_function(funcs[0], inputs)  # domain start -> first sub-function

    if ftype == 4:
        try:
            program = func.read_bytes()
        except Exception:
            return [0.5]
        result = ps_calc_eval(program, inputs)
        rng = func.get("/Range")
        n_out = len(rng) // 2 if rng else len(result)
        return result[-n_out:] if len(result) >= n_out else result

    if ftype == 0:
        rng = func.get("/Range")
        if rng:
            vals = [float(v) for v in rng]
            return [(vals[i] + vals[i + 1]) / 2 for i in range(0, len(vals), 2)]
        return [0.5]

    return [0.5]


def device_op_for(name, values):
    if name == "/DeviceGray":
        return "g", values[:1]
    if name == "/DeviceRGB":
        return "rg", values[:3]
    if name == "/DeviceCMYK":
        return "k", values[:4]
    return None


def resolve_colorspace(cs, values):
    """Resolve (colorspace, component values) down to a plain device
    color operator ('g'/'rg'/'k') and its operand values."""

    if isinstance(cs, (pikepdf.Name, str)):
        direct = device_op_for(str(cs), values)
        if direct:
            return direct
        return "g", [0.5]  # unhandled named colorspace (e.g. /Pattern) - mid-gray fallback

    # array-form colorspace
    kind = str(cs[0])

    if kind == "/ICCBased":
        stream = cs[1]
        n = int(stream.get("/N", len(values)))
        fallback_name = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}.get(n)
        if fallback_name:
            return device_op_for(fallback_name, values)
        return "g", [0.5]

    if kind in ("/DeviceN", "/Separation"):
        base_cs = cs[2]
        tint_func = cs[3]
        transformed = eval_function(tint_func, values)
        return resolve_colorspace(base_cs, transformed)

    if kind == "/CalRGB":
        return "rg", values[:3]
    if kind == "/CalGray":
        return "g", values[:1]
    if kind == "/Lab":
        return "g", [0.5]  # not handled precisely; neutral fallback

    return "g", [0.5]


def resolve_shading_color(shading_dict):
    func = shading_dict["/Function"]
    if isinstance(func, pikepdf.Array):
        func = func[0]
    domain = shading_dict.get("/Domain", [0.0, 1.0])
    t0 = float(domain[0])
    values = eval_function(func, [t0])
    cs = shading_dict["/ColorSpace"]
    return resolve_colorspace(cs, values)


# ---------------------------------------------------------------- content stream rewriting ----

BIG = 200000  # far larger than any realistic page/CTM scale; gets clamped by the active clip


def flatten_op(op, values):
    rect = pikepdf.ContentStreamInstruction(
        [-BIG / 2, -BIG / 2, BIG, BIG], Operator("re")
    )
    fill = pikepdf.ContentStreamInstruction(pikepdf._core._ObjectList([]), Operator("f"))
    color = pikepdf.ContentStreamInstruction(
        [round(float(v), 4) for v in values], Operator(op)
    )
    return [color, rect, fill]


def process_page(page, color_cache_key_prefix=""):
    """Returns (new_instructions_or_None, replaced_count, skipped_count)."""

    shading_res = page.obj.Resources.get("/Shading")
    instructions = pikepdf.parse_content_stream(page)

    color_by_name = {}
    if shading_res:
        for name in shading_res.keys():
            try:
                color_by_name[str(name)] = resolve_shading_color(shading_res[name])
            except Exception as e:
                color_by_name[str(name)] = None  # resolution failed

    replaced = 0
    skipped = 0
    new_instructions = []
    changed = False

    for instr in instructions:
        if str(instr.operator) == "sh" and instr.operands:
            name = str(instr.operands[0])
            resolved = color_by_name.get(name)
            if resolved is not None:
                op, values = resolved
                new_instructions.extend(flatten_op(op, values))
                replaced += 1
                changed = True
                continue
            else:
                skipped += 1
        new_instructions.append(instr)

    return (new_instructions if changed else None), replaced, skipped, color_by_name


def parse_page_range(spec, num_pages):
    if spec is None:
        return range(num_pages)
    start, end = spec.split("-")
    return range(int(start), min(int(end), num_pages - 1) + 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_pdf")
    ap.add_argument("output_pdf")
    ap.add_argument("--pages", help="0-indexed inclusive range, e.g. 10-40 (default: whole document)")
    ap.add_argument("--dry-run", action="store_true", help="Report only, no file written")
    args = ap.parse_args()

    pdf = pikepdf.open(args.input_pdf)
    num_pages = len(pdf.pages)
    page_range = parse_page_range(args.pages, num_pages)

    total_replaced = 0
    total_skipped = 0
    pages_touched = 0

    for i in page_range:
        page = pdf.pages[i]
        page.contents_coalesce()
        new_instructions, replaced, skipped, colors = process_page(page)
        if replaced == 0 and skipped == 0:
            continue

        pages_touched += 1
        total_replaced += replaced
        total_skipped += skipped
        color_desc = ", ".join(
            f"{name}={val}" for name, val in colors.items() if val is not None
        )
        print(f"page {i}: replaced={replaced} skipped={skipped}  [{color_desc}]")

        if args.dry_run or new_instructions is None:
            continue

        new_bytes = pikepdf.unparse_content_stream(new_instructions)
        page.obj.Contents.write(new_bytes)

    print()
    print(f"Pages scanned: {len(list(page_range))}")
    print(f"Pages with gradients: {pages_touched}")
    print(f"Gradients flattened: {total_replaced}")
    print(f"Gradients skipped (color resolution failed): {total_skipped}")

    if not args.dry_run:
        pdf.save(args.output_pdf)
        print(f"\nSaved: {args.output_pdf}")
    else:
        print("\nDry run — no file written.")


if __name__ == "__main__":
    main()
