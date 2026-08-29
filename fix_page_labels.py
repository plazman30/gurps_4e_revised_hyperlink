#!/usr/bin/env python3
"""
fix_page_labels.py -- Interactively rebuild a PDF's /PageLabels (the
printed page numbers a PDF viewer shows, independent of physical page
index) for the common scanned-book layout: an optional front cover,
some roman-numeral front matter, the arabic-numbered body, and an
optional back cover that can sit anywhere in the file (front matter,
the body, or the very end) rather than only ever being the last page.

USAGE:
    python3 fix_page_labels.py INPUT.pdf [OUTPUT.pdf] [--tui]

    OUTPUT.pdf is optional -- if omitted, writes INPUT-renumbered.pdf
    next to the input file. --tui replaces the plain y/n prompts with a
    single full-screen Textual form (a checkbox, a 3-way choice for the
    back cover, and a page-1 field, all editable at once, mouse or
    keyboard) that ends on a preview screen showing every resulting
    page-label range before anything is written; Esc quits from either
    screen, and rejecting the preview returns to the form with everything
    you already entered still filled in.

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
    pip install textual   # only needed for --tui
"""

import sys
import shutil
from pathlib import Path
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


def build_tui_app(in_path, out_path, page_count):
    """Lazily imports Textual and builds (but does not run) the wizard App:
    a single form screen collecting the same three answers gather_inputs()
    asks sequentially, then a preview of the computed label ranges before
    confirming. Split out from run_tui() so it can be driven headlessly
    via App.run_test() in tests, without spawning a real terminal.

    Reads back as app.is_cover / app.back_cover_idx / app.page1_idx /
    app.confirmed once the app exits (run_tui() below packages these into
    the same return shape gather_inputs() uses)."""
    from textual.app import App, ComposeResult
    from textual.screen import Screen
    from textual.containers import Vertical, VerticalScroll, Horizontal
    from textual.widgets import (
        Header, Footer, Static, Button, Input, Checkbox, RadioSet, RadioButton,
    )
    from textual import on

    WIZARD_CSS = """
    Screen {
        align: center middle;
    }
    .box {
        width: 64;
        max-height: 100%;
        border: round $accent;
        padding: 1 2;
    }
    .subtitle {
        color: $accent;
        text-style: bold;
    }
    .field-label {
        margin-top: 1;
    }
    .hint {
        color: $text-muted;
    }
    .error {
        color: $error;
        text-style: bold;
    }
    Horizontal {
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    Button {
        margin: 0 1;
    }
    """

    class FormScreen(Screen):
        CSS = WIZARD_CSS
        BINDINGS = [
            ("escape", "quit_wizard", "Quit"),
            ("pagedown", "scroll_form_down", "Scroll down"),
            ("pageup", "scroll_form_up", "Scroll up"),
            ("enter", "confirm_radio", "Confirm"),
        ]

        def compose(self) -> ComposeResult:
            yield Header()
            with VerticalScroll(classes="box", can_focus=False):
                yield Static("Page label settings", classes="subtitle")
                yield Checkbox("Page 1 is the cover", value=True, id="cover",
                                compact=True)
                yield Static("Back cover:", classes="field-label")
                with RadioSet(id="backcover_mode"):
                    yield RadioButton("Last page", id="mode_last", compact=True)
                    yield RadioButton("Specific page (enter below)",
                                       id="mode_specific", compact=True)
                    yield RadioButton("No back cover", value=True,
                                       id="mode_none", compact=True)
                yield Input(placeholder="back cover page number",
                            restrict=r"[0-9]*", id="backcover_page", compact=True)
                yield Static("What PDF page is actually page 1?",
                             classes="field-label")
                yield Input(placeholder=f"1-{self.app.page_count}",
                            restrict=r"[0-9]*", id="page1", compact=True)
                yield Static("", id="error", classes="error")
                with Horizontal():
                    yield Button("Preview", id="preview", variant="success", compact=True)
                    yield Button("Quit", id="quit", compact=True)
            yield Footer()

        def on_mount(self):
            self.query_one("#page1", Input).focus()

        @on(Button.Pressed, "#preview")
        def _preview_btn(self):
            self._submit()

        @on(Button.Pressed, "#quit")
        def _quit_btn(self):
            self.app.exit()

        @on(Input.Submitted, "#backcover_page")
        def _backcover_page_submitted(self):
            self.query_one("#page1", Input).focus()

        @on(Input.Submitted, "#page1")
        def _page1_submitted(self):
            self._submit()

        def action_quit_wizard(self):
            self.app.exit()

        def action_scroll_form_down(self):
            self.query_one(".box").scroll_page_down()

        def action_scroll_form_up(self):
            self.query_one(".box").scroll_page_up()

        def action_confirm_radio(self):
            # Workaround for a real Textual quirk (confirmed in a bare,
            # from-scratch RadioSet with none of this app's code involved):
            # RadioSet.BINDINGS declares "enter,space" together for
            # toggle_button, but Enter alone silently does nothing --
            # _selected (the arrow-key cursor) moves fine, pressed_button
            # just never updates -- while Space works correctly every
            # time. Checkbox (the same ToggleButton base class) and
            # Button both handle Enter fine on their own; only RadioSet
            # is affected. Since this key clearly isn't being consumed by
            # RadioSet's own (non-functional) binding, it reaches this
            # screen-level fallback, which just re-invokes the exact same
            # action Space already triggers successfully.
            radio_set = self.query_one("#backcover_mode", RadioSet)
            if self.focused is radio_set:
                radio_set.action_toggle_button()

        def _submit(self):
            error_box = self.query_one("#error", Static)
            is_cover = self.query_one("#cover", Checkbox).value

            pressed = self.query_one("#backcover_mode", RadioSet).pressed_button
            mode_id = pressed.id if pressed else None

            back_cover_idx = None
            if mode_id == "mode_last":
                back_cover_idx = self.app.page_count - 1
            elif mode_id == "mode_specific":
                raw = self.query_one("#backcover_page", Input).value.strip()
                if not raw:
                    error_box.update(
                        "Enter a back cover page number, or choose a "
                        "different back cover option.")
                    return
                n = int(raw)
                if not (1 <= n <= self.app.page_count):
                    error_box.update(
                        f"Back cover page must be between 1 and {self.app.page_count}.")
                    return
                back_cover_idx = n - 1

            page1_raw = self.query_one("#page1", Input).value.strip()
            if not page1_raw:
                error_box.update("Enter what PDF page is actually page 1.")
                return
            page1_n = int(page1_raw)
            if not (1 <= page1_n <= self.app.page_count):
                error_box.update(
                    f"Page 1 must be between 1 and {self.app.page_count}.")
                return
            page1_idx = page1_n - 1

            errors = []
            if is_cover and page1_idx == 0:
                errors.append("Page 1 can't be both the cover and printed page 1.")
            if back_cover_idx is not None and back_cover_idx == page1_idx:
                errors.append("The back cover page can't also be printed page 1.")
            if is_cover and back_cover_idx == 0:
                errors.append(
                    "The back cover can't be the same page as the front cover.")
            if errors:
                error_box.update("  ".join(errors))
                return

            error_box.update("")
            self.app.is_cover = is_cover
            self.app.back_cover_idx = back_cover_idx
            self.app.page1_idx = page1_idx
            self.app.push_screen(PreviewScreen())

    class PreviewScreen(Screen):
        CSS = WIZARD_CSS
        BINDINGS = [("y", "write", "Write"), ("n", "go_back", "Back"),
                    ("escape", "quit_wizard", "Quit")]

        def compose(self) -> ComposeResult:
            ranges = compute_label_ranges(
                self.app.page_count, self.app.is_cover,
                self.app.back_cover_idx, self.app.page1_idx)
            self.ranges = ranges
            lines = []
            for start_idx, end_idx, kind, start_value in ranges:
                first = render_label(kind, start_value)
                if end_idx == start_idx:
                    lines.append(f"PDF page {start_idx + 1}: {first}")
                else:
                    last_value = (start_value + (end_idx - start_idx)
                                  if kind != "cover" else start_value)
                    last = render_label(kind, last_value)
                    lines.append(
                        f"PDF pages {start_idx + 1}-{end_idx + 1}: {first} .. {last}")
            yield Header()
            with Vertical(classes="box"):
                yield Static("Preview", classes="subtitle")
                yield Static("\n".join(lines), id="preview-list")
                yield Static(f"Write to {self.app.out_path}?")
                with Horizontal():
                    yield Button("Write (Y)", id="write", variant="success", compact=True)
                    yield Button("Back (N)", id="back", compact=True)
            yield Footer()

        @on(Button.Pressed, "#write")
        def _write_btn(self):
            self.action_write()

        @on(Button.Pressed, "#back")
        def _back_btn(self):
            self.action_go_back()

        def action_write(self):
            self.app.confirmed = True
            self.app.exit()

        def action_go_back(self):
            self.app.pop_screen()

        def action_quit_wizard(self):
            self.app.exit()

    class LabelWizardApp(App):
        TITLE = f"fix_page_labels.py -- {Path(in_path).name}"

        def __init__(self):
            super().__init__()
            self.in_path = in_path
            self.out_path = out_path
            self.page_count = page_count
            self.is_cover = None
            self.back_cover_idx = None
            self.page1_idx = None
            self.confirmed = False

        def on_mount(self):
            self.push_screen(FormScreen())

    return LabelWizardApp()


def run_tui(in_path, out_path, page_count):
    """Runs the wizard from build_tui_app() in a real terminal. Returns
    (is_cover, back_cover_idx, page1_idx), or None if the user quit
    without confirming."""
    app = build_tui_app(in_path, out_path, page_count)
    app.run()
    if not app.confirmed:
        return None
    return app.is_cover, app.back_cover_idx, app.page1_idx


def main():
    argv = sys.argv[1:]
    use_tui = "--tui" in argv
    argv = [a for a in argv if a != "--tui"]

    if len(argv) not in (1, 2):
        print("Usage: python3 fix_page_labels.py INPUT.pdf [OUTPUT.pdf] [--tui]")
        sys.exit(1)
    in_path = argv[0]
    if len(argv) == 2:
        out_path = argv[1]
    else:
        p = Path(in_path)
        out_path = str(p.with_name(f"{p.stem}-renumbered{p.suffix}"))

    try:
        with pikepdf.open(in_path) as probe:
            page_count = len(probe.pages)
    except FileNotFoundError:
        sys.exit(f"Error: {in_path!r} does not exist.")
    except PermissionError:
        sys.exit(f"Error: permission denied reading {in_path!r}.")
    except pikepdf.PdfError as e:
        sys.exit(f"Error: {in_path!r} doesn't look like a valid PDF ({e}).")

    if use_tui:
        result = run_tui(in_path, out_path, page_count)
        if result is None:
            sys.exit("Aborted.")
        is_cover, back_cover_idx, page1_idx = result
    else:
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
