# CLAUDE.md

Context for Claude Code picking up this project. This tool grew out of a long,
iterative debugging session against a real book (GURPS Basic Set, 4th Edition
Revised) rather than being designed up front, and a lot of that time went into
finding bugs that don't announce themselves — they just silently produce a
*plausible-looking but wrong* result. Read the "Known bugs already found and
fixed" section before touching the matching logic; several of these will
reappear if that code gets rewritten from a clean-room description of what it
"should" do instead of preserved as-is.

## What this project does

Auto-hyperlinks in-text page and chapter references in a PDF (originally
built for GURPS sourcebooks, and the detection architecture is mostly
generic, but each publisher's actual reference grammar/conventions needs
its own verified script — see `hyperlink_pdf_mongoose.py` for Mongoose
Publishing's Traveller line, forked from the GURPS version once real
testing found genuine differences, documented in bugs #20-#25). Given a
PDF with plain text like "see p. 208" or "Chapters 11-13", it finds every
such reference, works out which physical page it means, and inserts a
clickable link — without needing any external lookup table, without touching
already-correct links (e.g. a publisher's native Table of Contents), and
without linking a reference that's actually citing a *different* book.

## Files

| File | Purpose |
|---|---|
| `hyperlink_pdf_universal.py` | **Current active development version for GURPS books — start here for those.** Superset of everything below: page references, Index, chapter references (including comma-separated lists like "Chapters 2, 4, and 6"), GURPS book-code shorthand (`p. B123`), an auto-detected cross-book trigger word (pulled from the PDF's own title metadata instead of hardcoded "GURPS"), a known-title allowlist for bare italicized citations ("High-Tech, pp. 13-15" with no "GURPS" prefix), a TOC self-hyperlinking pass for books that ship without one (see below), and — since bug #38 — an optional `/PageLabels`-based lookup path for page-number resolution, used when the labels are trustworthy, that handles a multi-offset combined book the single-offset footer vote alone cannot. Validated against multiple real GURPS books, including a non-Basic-Set supplement (GURPS High-Tech: Electricity and Electronics) and GURPS Space specifically for the TOC feature. |
| `hyperlink_pdf_mongoose.py` | **First real non-GURPS test, and the current version for Mongoose Publishing's Traveller line — both 2nd edition and 1st edition.** A fork of `hyperlink_pdf_universal.py`'s logic, not a from-scratch rewrite — same architecture (footer-offset page-label detection, TOC/Index protection, cross-book filtering layers, rect-safety checks), adapted where real Mongoose books actually diverged from GURPS conventions. Verified against four distinct sub-products in the line: the 2e Traveller Core Rulebook/Companion/High Guard/Aliens of Charted Space set (bugs #20-#25), the 2300AD boxed set (bug #26), 1st-edition Traveller — Core Rulebook, two Alien Modules, two numbered "Little Black Book" reprints (Mercenary, Robot), Cosmopolite, and two Sector sourcebooks (bugs #28-#29), and, separately again, both volumes of *Aliens of Charted Space* itself (bug #30). 1e uses a completely different `/Info Title` naming convention (`"Book 9: Robot"`); the *Aliens of Charted Space* pass turned up a real same-book false-positive class (`title_after()`/`title_nearby()` mistaking a book's own chapter name for another product, bug #29) and a heading-detection gap on a book whose "CONTENTS" heading uses a smaller, faux-bold-doubled rendering the original bug #20 heuristics never saw (bug #30) — neither of which showed up in the sub-products tested before it. This confirms the "Known open limitations" prediction below was wrong in specifics but right in spirit — nothing crashed, but several features silently would have found nothing (or wrongly skipped real links) without these changes, and testing some sub-products never fully covered the others (bugs #26, #29, #30, #31, #32, #33, #34, #35, #36, #37). Two of the nine 1e test books (a sector gazetteer, an alphabetized encyclopedia) legitimately have zero internal page citations at all — confirmed by a direct full-text search, not assumed — so "0 links added" there is correct output, not a miss. See bugs #20-#37 below for exactly what differs and why; kept as a fully separate script rather than adding publisher-conditional branches to `hyperlink_pdf_universal.py`, matching the precedent set by `combine_gurps_basic_set.py` (bug #19) of forking instead of generalizing a single-book-family assumption. |
| `hyperlink_pdf.py` | The original stable, verified version predating the universal rewrite. Links `p. NNN` / `pp. NNN-NNN` page references and Index-style bare numbers only — no chapters, no TOC self-linking, no book-code/italic-title cross-book detection. Kept as a known-good fallback reference point. |
| `hyperlink_pdf_v2_chapters.py` | Intermediate version, superseded by `hyperlink_pdf_universal.py`. Kept for history; no reason to use it over the universal version now. |
| `crop_to_center.py` | Unrelated preprocessing tool: crops mismatched left/right margins so text is centered. Not required for hyperlinking; only relevant if starting from a raw, uncropped scan/export. |
| `fix_page_labels.py` | Unrelated to hyperlinking (the hyperlinker scripts never read `/PageLabels` at all -- they detect page numbering from actual printed footer/header text, per the "Nothing about page numbering is hardcoded" bullet above). Interactively rebuilds `/PageLabels` for a scanned book's cover + roman-numeral front matter + arabic body layout, purely for what a PDF viewer's own UI (Acrobat's page nav, thumbnail panel) displays. Asks 3 questions (is page 1 the cover; where's the back cover -- last page, a specific page, or none, since it doesn't have to be at the end; which PDF page is printed page "1"), labels both covers as the constant text "Cover" (a `/PageLabels` entry with `/P` set and no `/S`, so no number is generated at all), and fills roman/arabic numbering around them. The core logic (`compute_label_ranges()`) is a pure function of `(page_count, is_cover, back_cover_idx, page1_idx)` with no I/O, kept separate from the interactive prompting specifically so it can be unit-tested directly without simulating stdin -- verified against 6 scenarios including the two genuinely tricky ones (the back cover sitting in the *middle* of the front matter, and in the *middle* of the arabic body, not just at the very end) before ever touching a real PDF. Writes the `/PageLabels` number tree via `pikepdf` directly (not `pypdf`'s writer/append pattern -- see bugs #6/#7 for why that's avoided whenever a page-tree rebuild isn't otherwise required), and the written labels were independently cross-checked against `pypdf`, `PyMuPDF`, and raw `pikepdf` dictionary inspection -- all three agreed exactly. A `--tui` flag (`run_tui()`, building on `build_tui_app()`) adds a [Textual](https://textual.textualize.io/) front end to the exact same three questions, reusing `compute_label_ranges()`/`write_page_labels()`/`render_label()` unchanged rather than duplicating any logic -- it only replaces `gather_inputs()`'s plain `input()` loop. An earlier version of this used the standard-library `curses` module with one screen per question (`CoverScreen` -> `BackCoverYesNoScreen` -> ... -> `PreviewScreen`); switched to Textual (also lazy-imported, so the default plain-prompt mode never needs it installed) specifically because Textual ships `App.run_test()`, a proper headless test harness (`async with app.run_test() as pilot: await pilot.press("y")`) that drives the real app logic without a terminal at all, and because it works identically on Windows with no extra OS-specific package (curses needs the separate `windows-curses` package there). The per-question screens were then collapsed into a single `FormScreen` (checkbox + `RadioSet` for the back cover + a page-1 `Input`, all live at once) still followed by the same `PreviewScreen` -- since `PreviewScreen` is pushed on top of the one `FormScreen` instance rather than a fresh screen per step, rejecting the preview and popping back to the form costs nothing extra: Textual's screen stack keeps the form's widget state (every field's current value) exactly as the user left it, with no manual save/restore code needed. `build_tui_app()` is deliberately split out from `run_tui()` (which just calls `.run()` on it for real use) so tests can grab an unstarted app instance and drive it via `run_test()`.

**A real, reproducible bug was found switching to the form layout, not just a cosmetic one**: at the default terminal size Textual's own test harness uses (80x24 -- also an extremely common real terminal size), clicking `#cover`/`#mode_last`/etc. silently did nothing (no exception, no state change, not even a focus change) instead of toggling, while the exact same click code worked fine at a taller size (80x50). Root cause: `Checkbox`/`RadioButton`/`Input` all default to a bordered, 3-row-tall rendering in this Textual version, and the form's five stacked fields (checkbox, 3-way radio, two inputs) don't fit in 24 rows at that height, forcing the `VerticalScroll` wrapper to actually engage scrolling -- and `pilot.click(selector)`'s screen-coordinate math doesn't correctly account for a scrolled ancestor container, so clicks land on the wrong cell (or, once already scrolled, on a `y` coordinate `OutOfBounds` entirely). This was caught by exactly the same *"a clean run isn't sufficient, check specific behavior"* discipline this file has always argued for: the click calls didn't raise, `app.confirmed` just quietly stayed at its default rather than reflecting what was clicked, which is precisely the "plausible-looking but wrong" failure shape the top of this document warns about. Fixed at the root rather than papered over -- passing `compact=True` to every `Checkbox`/`RadioButton`/`Input`/`Button` in the form removes their borders (1-row-tall instead of 3), which makes the whole form fit in 24 rows without scrolling ever engaging, sidestepping the click-math bug entirely rather than working around it. `VerticalScroll` is kept as a defensive fallback for a pathologically small terminal, but the common case now never needs it. **If this form grows more fields in the future and starts needing to scroll again, re-verify clicks still land correctly at 80x24 before trusting a "looks right" headless test** -- the bug here produced zero errors, only silently-wrong state.

The same five scenarios verified under the curses version were re-verified against the form, each checked two ways: headlessly via `run_test()` (reading `app.is_cover`/`app.back_cover_idx`/`app.page1_idx`/`app.confirmed` directly, no PDF I/O, using `pilot.click()` for the checkbox/radio/buttons and `pilot.press()` for typing), and once end-to-end through a real pseudo-terminal (`pty.openpty()`) exercising the actual `run_tui()` -> file-write path, both cross-checked against `pypdf`'s independently-read output labels: the basic cover/back-cover-last/page-1 happy path; `Esc` quitting cleanly; unchecking the cover checkbox and leaving the back-cover radio at its "No back cover" default; selecting "Specific page" and hitting the contradiction error (`page 1` answered as both the cover and printed page 1), confirmed to block in place on `FormScreen` with the error text populated and `app.confirmed` still `False`, then correcting the field and resubmitting successfully; and rejecting the preview then resubmitting unchanged, confirming the form's prior answers (the exact `RadioSet` selection and `Input` text) were still there without needing to re-enter anything. One test-harness-only pitfall worth remembering for future tests on this form: clicking an `Input` to refocus it does **not** select-all its existing text (`select_on_focus` didn't behave that way here) -- backspacing without first clearing the field with `end` + repeated backspace just prepends/appends to the old value instead of replacing it, which produced one initially-confusing false test failure before being traced to the test script, not the app.

A follow-up bug check (headlessly probing every widget's `Input.Submitted`/`Button.Pressed` handler for gaps, not just re-running the five already-verified scenarios) found a real, user-facing asymmetry: pressing Enter in `#page1` submits the whole form, but pressing Enter in `#backcover_page` did **nothing at all** -- no error, no navigation, focus didn't even move, confirmed via `app.screen.focused.id` staying `"backcover_page"` before and after. Root cause: only `#page1` had an `Input.Submitted` handler bound; `#backcover_page` had none, so Textual's default (no-op) handling applied. Fixed by adding `@on(Input.Submitted, "#backcover_page")` that moves focus to `#page1` -- deliberately *not* wired to call `_submit()` directly, since at the point a user has just finished typing the back-cover page, `#page1` is very likely still empty and an immediate full-form submit would just bounce them into the "enter what PDF page is actually page 1" error instead of taking them to that field to fill it in. Verified with the full five-scenario suite re-run afterward (all unchanged) plus the specific new case: pressing Enter in `#backcover_page` now moves focus to `#page1` exactly, confirmed via `app.screen.focused.id`.

A second follow-up check -- this time walking Tab through every widget on `FormScreen` and printing what actually had focus at each step, since keyboard-only Tab-order navigation hadn't been exercised at all yet -- found a genuine dead stop: the tab order came back as `page1 -> preview -> quit -> <nothing> -> cover -> ...`, one step landing on a widget with no `id` at all. Root cause: `VerticalScroll` (the `.box` wrapper added for the small-terminal fix above) is focusable by default in Textual, since a scrollable container needs focus to accept keyboard-driven scrolling -- and it was never given an `id`, so a naive check for "which field lost focus" (`getattr(widget, "id", None)`) printed `None`, which reads exactly like a real focus-loss bug until you check the widget's *type*, not just its `id` (`type(app.screen.focused).__name__` showed `VerticalScroll`). Every Tab cycle wasted one keystroke landing on this invisible, functionally useless stop with no visible focus indicator. Fixed with `VerticalScroll(classes="box", can_focus=False)` -- safe to disable here specifically because the `compact=True` fix above already means the form fits in 24 rows without ever needing to scroll in the common case, so keyboard-driven scroll-via-focus on this container was never actually load-bearing. `PreviewScreen` was checked too, for the same class of bug: it uses a plain `Vertical`, not `VerticalScroll`, and its own Tab order (`write` <-> `back`, no dead stops) was already clean, confirming the fix was correctly scoped to the one container that actually needed it rather than applied speculatively everywhere. Verified with the same three-layer check as every other fix here: the five-scenario `run_test()` suite unchanged, a dedicated Tab-cycle test confirming the full sequence `page1 -> preview -> quit -> cover -> backcover_mode -> backcover_page -> page1` with no gaps, and one real-pseudo-terminal run cycling Tab six times back to `page1` and completing a full submit-and-write, cross-checked against `pypdf`. **General lesson for this file: a diagnostic that prints a widget's `id` as its stand-in identity will misreport "nothing focused" for any real, unlabeled widget that legitimately grabbed focus -- print the widget's type alongside its `id` before concluding focus was actually lost.**

A third follow-up check specifically audited the `can_focus=False` fix above for a side effect on the *rare* case it was reasoned to be safe for: a terminal genuinely too small to fit the form even at `compact=True` height. Reasoning alone isn't good enough per this file's own standard, so this was tested directly at a deliberately tiny `run_test(size=(80, 12))`, twelve rows -- and it confirmed a real, if narrow, regression: with the box no longer focusable, a keyboard-only user (no mouse -- realistic for anyone over a plain SSH session) had *no way at all* to scroll the hidden bottom of the form into view, since arrow keys/PageDown have no scrollable target to act on without focus. Mouse-wheel scrolling was separately confirmed unaffected (posting a raw `events.MouseScrollDown` directly, bypassing `Pilot`'s public API since it has no wheel-simulation method, moved `scroll_y` correctly regardless of `can_focus`) -- mouse users were never at risk, only keyboard-only ones. Fixed by adding explicit `pagedown`/`pageup` `BINDINGS` on `FormScreen` itself (confirmed unused by `Input`'s own `BINDINGS` first, so no key conflict) that call `.scroll_page_down()`/`.scroll_page_up()` on the `.box` container directly, regardless of which other widget currently holds focus -- restoring keyboard scroll access without reintroducing the box into the Tab cycle the previous fix removed it from. Verified at the same 80x12 size: repeated `pagedown` presses correctly advance `scroll_y` up to `max_scroll_y`, the `#preview` button becomes genuinely reachable (`region.y` inside the screen's visible height), and clicking it from there completes a real navigation to `PreviewScreen` -- plus the full six-scenario suite (five behavioral + the Tab-order check) re-confirmed unchanged at the normal 80x24 size. **General lesson: verifying a fix removes a bug is necessary but not sufficient -- when a fix specifically trades away a capability (here, focusability) by reasoning that the capability "was never load-bearing" for some case, that reasoning is itself a claim that needs testing at the edge it's reasoning about, not just at the common case the fix was aimed at.**

A fourth follow-up check exercised keyboard navigation *within* a focused widget for the first time (previous rounds covered mouse clicks and Tab between widgets, not arrow keys inside one) and found a genuine Textual-library quirk, confirmed to originate outside this app's own code before touching anything: arrow-key navigation moves `RadioSet`'s internal highlight cursor correctly (a private `_selected` index, distinct from `pressed_button` -- found by reading `textual.widgets._radio_set`'s source directly after `pressed_index` itself proved not to be the right thing to watch), but pressing **Enter** on the highlighted-but-not-yet-selected option silently does nothing, while **Space** on the exact same highlighted option works every time -- despite `RadioSet.BINDINGS` explicitly declaring `"enter,space"` together for the same `toggle_button` action. Confirmed this is a Textual bug/quirk in the installed version (not something in this file): reproduced identically in a from-scratch minimal app with a bare `RadioSet` and zero lines of this project's own code. Also confirmed the scope is narrow -- a bare `Checkbox` (the same `ToggleButton` base class RadioButton shares) and a bare `Button` both handle Enter correctly on their own, so this only affects `RadioSet` specifically, not toggle widgets generally. First test attempt looked like a failure but wasn't: pressing one "up" moved the cursor onto the *already-pressed* `mode_none` option, so "toggling" it via Enter was correctly a no-op (an exclusive radio group can't be toggled off by re-selecting its own current choice) -- re-tested by moving the cursor two steps onto a genuinely different option before pressing Enter, which is when the real gap showed up. Worked around (not just documented, since the fix is cheap and this is a real Textual limitation blocking legitimate keyboard-only use) by adding an `("enter", "confirm_radio", ...)` binding on `FormScreen` that re-invokes `radio_set.action_toggle_button()` -- the exact same method Space already calls successfully -- whenever the `RadioSet` currently holds focus. Confirmed no interference with the three other places Enter already works correctly on this screen (`#page1`'s `Input.Submitted` handler, the `Checkbox`, and the `Preview`/`Quit` buttons) by testing all four side by side: each still does exactly what it did before, and the new binding only ever fires when `self.focused is radio_set`. Verified with the full seven-scenario suite (the prior six plus a new fully-keyboard-driven flow: tab to the radio set, arrow to "Specific page," Enter to select it, tab through the remaining fields, submit) and once more through a real pseudo-terminal sending literal arrow-key escape sequences, cross-checked against `pypdf`.

A fifth follow-up check covered a mix of interactions not yet exercised (reverse Tab, a double-click on the Preview button, a mid-session terminal resize, and pasting into a `restrict`-limited `Input`) and confirmed all four already work correctly -- worth recording as *checked*, not just assumed, per this file's standing rule that a clean-looking result still needs to be tested rather than trusted. Double-clicking `#preview` looked alarming at first (`len(app.screen_stack)` came back `3`), but that wasn't a duplicate `PreviewScreen` push -- Textual's screen stack always carries its own base `Screen` at index 0, so the real stack was the expected `FormScreen` -> `PreviewScreen`, confirmed by pressing "back" once and landing cleanly on `FormScreen` with the stack shrinking to 2. Pasting non-digit text (simulated via posting a real `events.Paste` message, not just reading `Input.replace()`'s source) confirmed `restrict` rejects the *entire* paste atomically rather than partially inserting or truncating it -- `"abc123"` left the field empty, `"5x"` left a prior valid value untouched -- so `_submit()`'s bare `int(raw)` calls can never receive non-digit text through either typing or pasting.

The one real find this round was unrelated to the Textual rewrite itself: passing a nonexistent path, or a file that isn't a valid PDF, produced a raw Python traceback (`FileNotFoundError`/`pikepdf.PdfError` surfacing straight out of the initial `pikepdf.open(in_path)` probe in `main()`, uncaught) instead of a clean message -- a real usability gap for a tool whose own README walks non-technical users through double-click installers on both platforms; a typo'd filename shouldn't hand them a stack trace. Fixed by wrapping that first `pikepdf.open()` call in `main()` with `except FileNotFoundError` / `except PermissionError` / `except pikepdf.PdfError`, each producing a one-line `sys.exit(f"Error: ...")` message in the same voice as `gather_inputs()`'s own existing validation errors (`pikepdf.PdfError`'s own exception message is descriptive enough to include verbatim rather than replacing it). This is the earliest possible point to catch it -- before either input-gathering path (`gather_inputs()` or the TUI) even starts, so it applies to both modes identically. Verified directly: a nonexistent path and a plain text file renamed `.pdf` each now print a clean one-line error and exit 1, and the existing plain-prompt happy path was re-run afterward to confirm the `try`/`except` wrapping didn't disturb the success path.

A `detect_printed_page1()` auto-detect prototype was added later: instead of the user having to work out and type which PDF page is printed page "1" from scratch, it scans every page's footer for a printed arabic number -- the exact same technique (band=45, strip trailing `.`/`,`, vote on the most common `pdf_index - printed_number` offset) as `hyperlink_pdf_universal.py`'s own `detect_page_labels()`, lazily importing PyMuPDF (already a project dependency, just never previously needed by this pikepdf-only script) so its absence degrades to exactly the pre-existing behavior rather than breaking anything. Deliberately a **suggestion, never an auto-applied answer** -- it only pre-fills the `page1` prompt/field's default (Enter accepts it in plain mode; the TUI's `#page1` `Input` shows it pre-typed with a "Detected from footer text -- edit if wrong" hint underneath), consistent with this script's whole existing design of confirming every answer before writing, and with this project's repeated lesson (bugs #6/#7/#19 among others) that automated page-numbering logic keeps finding new ways to be silently wrong. Guards against a wrong or absent suggestion rather than presenting one with false confidence: requires at least `MIN_FOOTER_OBSERVATIONS` (3) agreeing footer reads and `MIN_FOOTER_AGREEMENT` (50%) of all observations, and separately rejects any prediction landing outside the document entirely -- both real, not theoretical, since the second guard is exactly what correctly keeps this from suggesting anything on a book whose own numbering doesn't start at "1" at all. Verified against the same four real GURPS 4E books used elsewhere in this file, checked against each book's own actual `/PageLabels` as ground truth (not just eyeballed): Characters, High-Tech, and Basic Set Fourth Edition Revised all detected the exact correct PDF index with high agreement (335/335, 255/255, and 584/611 respectively); Campaigns -- whose own printed numbering continues from 337 rather than starting at 1, since it's Book 2 of a two-volume set -- correctly returned no suggestion at all, confirmed to be for the right reason (the majority offset, voted with 238/238 agreement, predicts printed page "1" would fall at PDF index -334, caught and rejected by the out-of-range guard) rather than silently guessing something plausible-but-wrong. A full end-to-end run through the plain-mode prompts, accepting the suggested default with a blank Enter, was also confirmed to flow correctly through `gather_inputs()` -> `compute_label_ranges()` -> `write_page_labels()` and produce the expected arabic range starting exactly at the detected page.

**Testing against the Mongoose Traveller corpus (21 books) afterward found a real, confirmed limitation in the first version, not just a theoretical edge case.** Only 3 of those 21 books carry real embedded `/PageLabels` to check against at all; of those 3, the naive single-guess version got 1 right and 2 "wrong" -- but reading the actual footer text by hand (not just trusting either number) showed something more specific than a simple miss. One book (*LBB9: Library Data*) has embedded `/PageLabels` that flatly disagree with its own visibly printed footer numbers throughout (the page labeled "3" literally prints "2" in its footer, "4" prints "3", and so on) -- the detector was reading the real, visible numbers correctly; that file's own pre-existing metadata was what was actually wrong. The other (*MGP3800 Core Rulebook* 1E) exposed the real gap: its embedded label puts "1" on the bare cover, but the cover AND the copyright page after it both have zero visible footer text, so the first REAL evidence (footer "2") only appears two pages later than "1" -- the single-guess version always assumes there's exactly one blank page before the first visible number and landed one page too late, on the copyright page instead of the cover. The same pattern (cover + unnumbered copyright page, first visible digit is "2") turned out to be common across this corpus, not a one-off -- confirmed directly by reading real footer text on `MGP3800`, *Deneb Sector*, and 2300AD *Book 1*, all three identical in shape, versus *AdventureClassShips*, which is the confirmed-different case: its second page genuinely does print "1" in the footer, no extrapolation needed.

Fixed by having `detect_printed_page1()` return a 4th value, `ambiguous_from`: after computing `page1_idx` from the offset vote, it checks whether `page1_idx` itself has a directly-observed `(page1_idx, 1)` footer reading. If so (confirmed, e.g. `AdventureClassShips`), there's no ambiguity regardless of what precedes it. If not -- `page1_idx` is only an extrapolation from later pages' evidence -- it walks backward counting consecutive pages with **zero** footer digits of their own (any digit, not just ones matching the winning offset, since a page showing some other, unrelated number is still real evidence against page 1 being there and correctly stops the walk). Both `main()`'s plain-mode print and the TUI's `#page1` hint now name the flagged range explicitly ("PDF pages 1-2 have no visible page number of their own -- check that range") instead of presenting an extrapolated guess with the same confidence as a directly-confirmed one. **A precision bug in this fix's own first draft was caught before shipping it, by re-running the exact same verification rather than assuming the fix was correct because it compiled**: the initial version walked backward from `page1_idx` unconditionally, without first checking whether `page1_idx` itself had direct confirming evidence -- which flagged `AdventureClassShips` as ambiguous too (since the page *before* its confirmed "1" is a blank cover), even though there's real, direct proof its answer is exactly right. Fixed by checking `(page1_idx, 1) in observations` first and only walking backward when that's absent. Re-verified against all 9 books with either real ground truth or a directly-confirmed/refuted footer reading: `Characters`/`High-Tech` (GURPS, previously exact matches) now correctly show ambiguous with the true answer inside the flagged range; `Basic Set Fourth Edition Revised` and `AdventureClassShips` (both directly confirmed by a real visible "1") correctly show no ambiguity at all; `MGP3800`/`LBB9` (the two original mismatches) now flag a range that includes their real embedded "1" position; `Robot-renumbered` (the one exact match) stays an exact match. |
| `extract_links.py` / `apply_links.py` | A manifest-based pair for migrating a verified set of links from one copy of a book onto a *different* copy (e.g. a differently-cropped or differently-compressed export of the same content). Not part of the normal hyperlinking workflow — only useful if you have a known-good hyperlinked file and need to transplant its links elsewhere. |
| `remove_cross_book_links.py` | Standalone cleanup pass: scans an *already-linked* PDF and removes any link that was wrongly created for a different-book reference. Useful if the cross-book filter is later found to have missed a case. |
| `unlinked_report.py` | Audits a PDF and reports every reference-shaped piece of text that has no link, classified by likely reason (out of range / other-book title nearby / unexplained). The "unexplained" bucket is the useful one — anything there is probably a real gap. |
| `combine_gurps_basic_set.py` | Merges the GURPS Basic Set, 4E Characters and Campaigns PDFs into one file (deletes a few cut-content pages, splices the two front matters/TOCs together, moves both books' `II` pages to the end, relabels the merged front matter as sequential lowercase roman numerals, sets metadata + an open-to-Contents action), then optionally (`--hyperlink`, off by default) hyperlinks the result. Hardcodes the specific page labels to move/delete for this exact pair of books — not a general merger. Every page label is reconstructed from scratch and independently verified against the source labels before the merge step reports success. The merge step uses `pypdf`'s writer/append pattern (see bugs #6/#7 below) rather than `pikepdf` — that's normally avoided in this pipeline, but reordering/deleting pages here genuinely requires rebuilding the page tree, and the script explicitly reconstructs `/PageLabels` and `/Info` metadata afterward rather than assuming pypdf preserves them. The `--hyperlink` step is a **separate, later pass**, opening the just-written file fresh with PyMuPDF (`fitz`) — it does not touch or extend the pypdf writer object. Its reference-matching logic (regexes, cross-book detection, rect-safety checks) is a full inline copy of `hyperlink_pdf_universal.py`'s, kept independent on purpose since this is a one-off pipeline for exactly one merged file; but its page-number resolution is deliberately *not* copied from that script — see bug #19 below for why. |
| `castles_and_crusades_background_layer.py` | **Entirely unrelated to hyperlinking or GURPS/Mongoose** — developed against Troll Lord Games' Castles & Crusades line (Castle Keeper's Guide, Adventurers Backpack, Monsters & Treasure), brought into this repo as a second home for pikepdf-based PDF-structure utilities rather than living alone. Tags the full-page decorative background (parchment texture, paper grain) on each page as a toggleable Optional Content Group layer, or deletes it outright with `--remove`. Detection is **geometry-based, not naming- or order-based** -- it tracks the actual CTM (`q`/`Q`/`cm`) through each page's content stream and computes the *real on-page bounding box* of every `Do` (draw XObject) call, and only something covering ~85%-135% of the page's MediaBox (bleed tolerance) is even eligible as a background candidate. This was a deliberate rewrite forced by a real false-positive found during development: an earlier "whatever's drawn first, if something's drawn after it" heuristic mistook a title page's **logo banner** (drawn first, with real content after it) for the background in Adventurers Backpack -- toggling/removing it would have deleted actual logo artwork, not parchment. The same file also broke the "always has content drawn after it" assumption in the other direction: two pages are blank except for the background (a chapter-divider page), so a real background can legitimately have *nothing* drawn after it -- caught instead via a second signal, the same underlying image/form being reused on 2+ pages (`resolve_identity()`, which unwraps one level of Form-wrapping so re-wrapped copies of the same inner image still match). A full-page object that's both unique to one page *and* has nothing drawn after it (a cover, a standalone full-bleed illustration) is correctly left alone -- it's real content, not a background. Verified against all three test files for: background actually disappears (tag+bake-off and `--remove` both checked), TOC/bookmarks unchanged, all hyperlinks unchanged, page count unchanged. Known open gap: no handling yet for a background drawn via a tiling pattern (`/PatternType 1`) rather than a single Image/Form -- not seen in the three files tested, but plausible for a repeating texture. See `python3 castles_and_crusades_background_layer.py --help` for usage. |
| `extract_gurps_wraparound_cover.py` | **Entirely unrelated to hyperlinking** -- recovers hidden wraparound cover art (back cover + spine + front cover, all drawn on one page) from GURPS/Steve Jackson Games PDFs. The trick these PDFs use: `/MediaBox` is the full wraparound-art size, but `/CropBox` is deliberately set smaller (just the front-cover slice), so any ordinary PDF viewer only ever shows the cropped slice -- some self-hosted book-server thumbnailers (BookOrbit, Grimmory, Kavita) render straight from the MediaBox instead of respecting the CropBox, which is how the full art becomes visible there but nowhere else. Detection compares every page's MediaBox area to its CropBox area (`find_wraparound_page()`, default threshold 1.15x, tunable via `--min-ratio`) and picks the highest-ratio match rather than just the first one over threshold. Extraction (`extract_and_convert()`) is a pure box edit -- `page.set_cropbox(page.mediabox)` on a single selected page, saved with `garbage=3, deflate=True` -- copying every original vector object, embedded image, and embedded font through untouched, nothing re-rendered or recompressed. A companion SVG is also written via `get_svg_image(text_as_path=True)`, outlining every text run to vector paths so the SVG carries zero font dependencies (`<text>`/`<font>` element count of 0), safe to open or share without the source PDF's fonts installed. Confirmed source-side quirk worth knowing if this needs debugging on a new book: wraparound cover pages found so far are rotated 270 degrees in the source PDF, which carries through to the extracted PDF as-is (some viewers show it sideways until rotated) but renders upright in the SVG since `get_svg_image()` bakes in the page's own rotation transform -- confirmed directly in this repo (not just taken on faith from the original author's notes) with a synthetic double-wide, 270-degree-rotated test page: the extracted PDF's `/CropBox` came back exactly equal to `/MediaBox`, `page.rotation` was still `270`, the SVG had zero `<text>` elements, and its declared width/height came back swapped from the PDF's own (792x1224 vs. 1224x792) exactly as the rotate-then-bake-upright claim predicts. `--list` can flag more than one page as a candidate (e.g. a recto/verso pair) -- auto-detect always takes the single highest ratio, but use `--list` plus `-p PAGE_NUM` together if that picks the wrong one. Scope is deliberately narrow: only the MediaBox/CropBox wraparound pattern, no OCR, no color-space handling, no compression tuning -- kept as a small single-purpose script rather than folded into a general-purpose tool.

**Bug found testing against 4 real GURPS PDFs (three Basic Set/High-Tech titles plus a newer "Fourth Edition Revised" printing):** all four have two pages tied (or near-tied) for the highest MediaBox/CropBox ratio, and in three of the four that's harmless -- both candidate pages, fully expanded, render the byte-identical complete spread (confirmed via MD5 pixel hash, not just eyeballing), so picking either one is correct. The fourth (`GURPS_Basic_Set_Fourth_Edition_Revised.pdf`) is genuinely different and was an actual, confirmed wrong-output bug: the wraparound spread is split across the two pages instead of duplicated on both -- page 1 draws only the front cover with the entire back-cover/spine half of its own MediaBox left blank, page 2 draws only the back cover with the entire front-cover half left blank. `find_wraparound_page()` still picks one of them (same tie-breaking as always) and `extract_and_convert()` happily produces a "complete-looking" PDF/SVG pair with no error -- silently wrong output, not a crash, the exact failure shape this whole toolkit's other scripts have repeatedly warned about. Confirmed by rendering both pages' full MediaBox and looking at them (page 1: recognizable front cover on the right, solid near-black void on the left where the back cover should be; page 2: the mirror image) -- and confirmed the fix direction works by manually max-blending the two renders into one image, which reconstructs the real, complete cover exactly. Detected with `revealed_region_blank_fraction()`: after picking a page, render just the *revealed* region (the part outside the page's original CropBox, i.e. exactly the area a plain crop would never have shown) at low DPI and check what fraction of it is a single dominant color -- confirmed empirically on all four real books before wiring it in: ~0.42-0.47 for the three genuinely-complete pages, ~0.99 for both halves of the split book, a wide enough margin that the chosen 0.90 threshold isn't a close call.

**Fixed properly, not just flagged**: when the blank check fires, `find_complementary_page()` looks for another candidate page (same `min_ratio` threshold) whose own original CropBox barely overlaps the selected page's -- a strong signal it holds the other half -- and `merge_split_pages()` combines them into one complete page. This is a **vector-level copy via `show_pdf_page()`, not a rasterized blend**: text stays live text (confirmed -- the merged Revised-book output still has 8 real embedded fonts, not zero), images stay at original resolution, nothing is re-rendered, matching this script's whole reason for existing over just screenshotting a viewer. The two source pages' CropBoxes don't actually touch -- there's a spine-width gap neither page's own crop covers at all -- so `merge_split_pages()` temporarily widens each source page's CropBox out to the midpoint of that gap before embedding, so the merged result has no seam or blank strip where the two halves meet (confirmed by rendering the very first attempt without this: a clean vertical white gap exactly where the spine should be). Two real implementation bugs surfaced and got fixed while building this, both from the same root mistake -- computing "what does this page's own real content region look like" *after* something upstream had already expanded that page's CropBox out to the full MediaBox, at which point it trivially "overlaps" everything and looks just like the full page: `find_complementary_page()` needed the selected page's *original* CropBox passed in explicitly rather than re-reading `doc[selected_index].cropbox` (already-expanded) off the page, and `extract_and_convert()` needed to restore the probed page's CropBox back to its original value before attempting a merge, since `merge_split_pages()` reads it again independently. Both were caught by testing the actual integrated code path end-to-end (rendering the real output and finding the merge silently wasn't happening) rather than trusting the standalone prototype that had already worked. `extract_and_convert()` now returns which page it merged with (or `None`), and `main()` prints either a one-line "combined it with page N" note or, if no complementary page could be found, the same explicit warning as before pointing at `--list`/`-p` for a manual check -- the warning is a fallback now, not the primary behavior. Verified against all four real files: the three duplicate-page books are completely unaffected (identical output, byte-for-byte unchanged behavior), and the split book now produces one seamless, complete, vector-preserved cover automatically -- confirmed by rendering the actual final integrated output (not just the standalone prototype) and visually matching it against the known-correct spread. **General lesson, matching this project's own established pattern: a "pick the best/first candidate" heuristic that works on every book tested so far is still just an assumption until a book actually breaks it -- this one only surfaced by testing a fourth, newer printing that happened to use a different production process for the same publisher and same nominal cover structure. Second lesson: when a fix mutates shared state (a page's CropBox) for one purpose (measuring blankness) and a later step needs the pre-mutation state for a different purpose (finding/building the merge), restore it explicitly rather than assuming nothing downstream cares -- this exact mistake was made twice in one sitting, in two different functions, before being caught by testing the integrated path rather than the isolated prototype.** |
| `gurps_4e_revised_tag_borders_ocg.py` / `gurps_4e_revised_flatten_gradients.py` | **Entirely unrelated to hyperlinking**, and unlike the other pikepdf-based utilities above, purpose-built for one specific file's page design rather than a whole publisher's line: `GURPS_Basic_Set_Fourth_Edition_Revised.pdf`'s maroon/gold decorative border, which turns out to be one large axial `sh` (shading) gradient clipped to nearly the full page rather than a stroked rectangle, plus separate stroked picture-frame outlines around callout/sidebar boxes in the same accent color. Both scripts locate this content the same way: walk the content stream simulating the graphics-state stack (`q`/`Q`, clip region, stroke/fill color) so each drawing operator can be judged in the *actual* state it executes under, not just by looking at nearby bytes. `gurps_4e_revised_tag_borders_ocg.py` wraps matches in toggleable Optional Content Groups (reversible); `gurps_4e_revised_flatten_gradients.py` permanently replaces each `sh` with a solid fill sampled from the strong end of its color ramp, resolved down through the shading's own `/ColorSpace` (including a small PostScript-calculator interpreter for `/DeviceN`/`/Separation` tint-transform functions, since this file's gradients are defined in a custom ink space) -- both were verified against the actual target file in this repo (not just taken on faith): `gurps_4e_revised_flatten_gradients.py` resolved every gradient it found on a real page range with zero color-resolution failures, and `gurps_4e_revised_tag_borders_ocg.py`'s output diffed *pixel-identical* to the unmodified original at default layer settings (Ghostscript render + `PIL.ImageChops.difference`, the same method its own CLAUDE.md prescribes, since PyMuPDF/Preview don't reliably honor OCG visibility), then toggling "Page Border" off via `pikepdf` (not PyMuPDF, per that same caveat) correctly dropped the border *and* the footer text (which inherits an invisible white fill with the border layer that paints over it gone), and toggling "Border Text (fallback)" on alongside it correctly restored the footer in solid black -- confirming the three-layer design promised in its own docs actually works as described, not just that it runs without error. `gurps_4e_revised_tag_borders_ocg.py`'s own docs list two real bugs already found and fixed in its content-stream splicing (a hidden layer's color-setting operators still execute even though painting is suppressed, so an unscoped color change inside one hidden duplicate leaked into later same-page content with the layer off; and copying a marked-content span verbatim can leave `q`/`BT` unbalanced in either direction since spans aren't required to nest cleanly with graphics-state operators, corrupting everything drawn afterward on the page) -- worth reading in full before touching `rebalanced_copy()` or the OC-wrapping logic in `build_tagged_stream()`. A fourth layer, "Solid Edge Border" (default OFF), was added later at the user's request: a flat, solid-color 10pt strip, independent of and additive to the other three layers rather than a toggle over any of them. **First implementation was wrong and caught by the user, not by testing**: the first version drew a full four-sided picture-frame ring (top/bottom/left/right), which the user immediately corrected -- the intent was a real book's outer-edge chapter tab, meaning only the OUTSIDE (fore-)edge, never the inside (gutter) edge and never top/bottom. Fixed with `is_recto(page_index)`, which alternates which physical side is "outside" by page parity -- confirmed against this actual book's real text margins (not assumed): even PDF indices measure a 72pt left margin / 18pt right margin, odd indices the reverse, exactly the wide-gutter/narrow-fore-edge pattern of alternating recto/verso pages, so even index = recto = outside-is-right. Its color isn't hardcoded or user-supplied -- it's resolved per page from that same page's own "Page Border" gradient shading, by copying `gurps_4e_revised_flatten_gradients.py`'s color-resolution pipeline (`ps_calc_eval`/`eval_function`/`resolve_colorspace`/`resolve_shading_color`) into this script verbatim rather than importing it, matching this project's established fork-not-share convention. **A second real gap surfaced during verification of the corrected geometry, not a code bug but a test-methodology trap worth recording**: toggling the new layer ON and diffing against the original showed *zero* pixel difference anywhere -- alarming at first, but not a rendering failure. The new strip's resolved color and position exactly coincide with the pre-existing "Page Border" gradient's own already-solid outer margin (confirmed by sampling real pixels: the original page is already that exact gold RGB in that exact 10pt band, since the gradient's strongest ramp value -- the same value `resolve_shading_color()` picks -- IS the color the existing border already shows at the true edge). Painting an identical color over identical content is invisible by construction, not evidence the feature is broken; confirmed by instead toggling "Page Border" OFF alongside "Solid Edge Border" ON, which showed the new strip cleanly on the right edge only for an even-index (recto) page and the left edge only for an odd-index (verso) page, with no content on the opposite side or at top/bottom. **General lesson: a before/after pixel-diff coming back clean is only proof of "no visible change" -- when new content is deliberately designed to reuse an existing color, that result can mean either "nothing rendered" or "rendered exactly on top of an identical match," and only isolating the new layer from what it's colored to match can tell the two apart.**

A `--tui` flag was added later, at the user's request, for a Textual progress bar in place of plain scrolling per-page output -- useful specifically because a full real book here runs to ~600 pages, where plain mode's scroll makes it hard to tell how far along a long run actually is. Followed `fix_page_labels.py`'s own established split for this: the entire page-tagging loop (previously inline in `main()`) was pulled out unchanged into `process_pages()`, a pure generator with no printing or UI code, yielding `(page_index, counts, line_or_None)` for every page in the range in order (even untouched ones, so a progress bar driven by "one yield per page" tracks true overall progress, not just tagged-page progress) -- both the plain-text loop and `build_tui_app()`'s worker call this same generator, so there are not two copies of the tagging logic to keep in sync. The actual pikepdf work runs in a Textual background worker thread (`run_worker(..., thread=True)`), with `call_from_thread()` used for every widget update from that thread, so the progress bar and log redraw smoothly instead of the UI freezing for the whole run. Verified three ways: (1) a plain-mode dry run over a real 21-page range recorded as the ground truth (`page=21 box=20 text=31 edge=21`, pages_touched=21); (2) a headless `run_test()` run of `build_tui_app()` over the identical range came back with `finished=True`, identical totals, and the `ProgressBar` widget's own `.progress`/`.total` reading exactly `21/21`, confirming the refactor didn't change the underlying tagging logic at all, just how it's driven; (3) a real end-to-end run through an actual pseudo-terminal (`pty.openpty()`, matching `fix_page_labels.py`'s own real-PTY verification precedent) driving the real `--tui` CLI path against the real book, captured output containing the literal `"21 / 21"` progress text, sent a real `q` keypress once it appeared, and confirmed the process exited cleanly and the resulting saved PDF actually has all four OCGs and real tagged content on disk -- not just that the in-memory app state looked right. One test-harness pitfall hit and fixed along the way, not a bug in the script itself: an early version of the PTY driver called a plain blocking `os.waitpid(pid, 0)` after its own read-loop timeout, which hung indefinitely because the child Textual process was still alive waiting on a keypress that was never actually delivered on that run -- fixed by switching to `select.select()`-bounded reads with a hard deadline and unconditionally `SIGKILL`-ing the child before waiting, so a test-harness bug in driving the TUI can never itself hang the whole verification step.

The first version of `--tui` also included a `RichLog` panel that echoed every tagged page's counts as scrolling text under the bar -- the user asked for it to be just a progress bar instead, finding the log noisy for what's meant to be a simple progress indicator. Removed the `RichLog` widget and its per-page `log.write()` calls entirely rather than hiding/collapsing it; `run_tagging()` now only advances the `ProgressBar` and updates the header's `sub_title` ("N / total pages", then "Press q to continue" once done) -- the per-page detail this removed is still available via plain mode (no `--tui`) or the same final console summary `main()` prints once the app exits either way. Re-verified with the same three checks as the original `--tui` addition: the headless `run_test()` totals/progress came back byte-identical to before (`finished=True`, `21/21`, matching per-kind totals), a direct `app.query(RichLog)` after the run confirmed zero `RichLog` widgets remain, and a real pseudo-terminal run's raw captured screen (ANSI codes stripped) showed the "N / 21" counter genuinely advancing across multiple redraws with no log panel visible, followed by the normal saved-file summary printing to the terminal after quitting with `q` -- and the saved PDF still has all four real OCGs.

The user then asked for the `--tui` window to auto-close a few seconds after finishing instead of waiting for `q`. **First implementation was a real, confirmed deadlock, and it's the exact kind of bug this project's testing discipline exists to catch: it looked completely correct in the headless test and hung forever in a real terminal.** That version had the worker thread, right after finishing all pages, loop with `time.sleep(1)` three times (updating the countdown via `call_from_thread` each tick) and then call `self.call_from_thread(self.exit)` from that same worker thread. `run_test()` showed it exiting cleanly at ~3s every time; a real pseudo-terminal run (same `pty.openpty()`-based harness used throughout this file's TUI verification, with an explicit `TIOCSWINSZ` 80x24 size ruled out as the cause too) never exited at all, confirmed genuinely stuck -- not just slow -- via a direct `os.waitpid(pid, os.WNOHANG)` poll that kept returning "still alive" for a 40+ second window while `pdf.save()` alone was independently timed at under 4 seconds for this same file, ruling out "just a slow save" as the explanation. Root cause: Textual's `App.exit()` can wait for outstanding workers (including the very `run_worker(thread=True)` worker that's calling it) to wind down before it returns, but `call_from_thread()` blocks its *calling* thread until the callable finishes running on the main thread -- so the worker thread was blocked inside `call_from_thread(self.exit)` waiting for `exit()` to return, while `exit()` was (on the theory that best fit the evidence) waiting on that same worker to finish. A deadlock that `run_test()`'s simulated driver apparently doesn't reproduce, making it invisible to the one verification method this project otherwise treats as authoritative for Textual code -- worth remembering specifically because it contradicts the usual advice here to trust `run_test()` results. Confirmed by adding temporary file-based debug logging (a separate file, deliberately not stdout/stderr, since those are the exact pty streams that were captured and useless for diagnosis while the process was stuck) around every step of the shutdown sequence, then removing it once the fix was verified. Fixed by never calling `self.exit()` (or looping/sleeping) from the worker thread at all: the worker now calls `call_from_thread(self.start_auto_close)` exactly once, right as it finishes -- a single quick call that lets the worker return immediately afterward -- and `start_auto_close()` (already running on the main thread) schedules the countdown as a native Textual `set_interval(1, ...)` timer, with `self.exit()` only ever called from within that timer's own callback, long after the worker thread has already exited. Re-verified with the debug logging first (showing the exact expected sequence: `start_auto_close` entered -> interval scheduled -> worker returns -> three ticks -> `exit()` called -> `exit()` returns, no gaps), then with that instrumentation removed, across 4 repeated real-pty runs with no flakiness (7.5-7.6s consistently), each confirmed to still produce a correctly-tagged, all-four-OCG output file matching the same range and totals as every other `--tui` verification in this file. **General lesson for this project's Textual work, extending `fix_page_labels.py`'s own precedent of real-terminal-only bugs: a deadlock between a background worker thread and the app's own shutdown path is a distinct failure class from the rendering/input-focus bugs found there, and it's one `run_test()` specifically failed to surface here -- any future cross-thread call into `self.exit()` (or anything that might internally wait on worker completion) needs a real-pty check before being trusted, even after a clean `run_test()` pass.** |

## Core architecture

- **Nothing about page numbering is hardcoded.** The printed-page-label
  scheme (roman front matter, arabic body, whatever offset applies) is
  detected by scanning every page's footer/header band for digit tokens and
  taking the *mode* of `(pdf_index - printed_number)` across the whole
  document. This is robust to a handful of noisy/wrong footer reads but
  assumes a single offset for the whole book — confirmed broken in
  practice by bug #19, where a file spliced together from two
  independently-paginated books defeated it outright (`combine_gurps_basic_set.py`
  worked around it locally there, rather than fixing it in this function).
  `hyperlink_pdf_universal.py` itself since gained a second path for
  exactly this case (bug #38): when the PDF's own `/PageLabels` are
  present and agree with the real footer numbers on most pages, a direct
  `printed_number -> pdf_index` dict is used instead of the single-offset
  vote — but only for the individual page-label entries that a page's own
  footer directly confirms, never for one that exists purely as metadata
  with nothing backing it (also bug #38, a real regression found in
  review). This helps only when a PDF happens to carry trustworthy labels
  in the first place; a book with no `/PageLabels` at all, or a
  fundamentally different numbering scheme (e.g. per-chapter restarts),
  still falls back to the single-offset vote and its same limitation.
- **The Table of Contents is protected implicitly, and self-hyperlinked if
  it appears to lack links entirely.** Protection: before inserting any
  link anywhere in the book, the code checks whether that spot is already
  linked, and a publisher's native TOC already has its own correct links,
  so nothing needs to know "this is TOC, don't touch it" as a special case.
  Self-linking (added later, in `hyperlink_pdf_universal.py` only):
  `toc_already_hyperlinked()` compares how many TOC lines look like
  dot-leader entries (ending in a bare page number) against how many links
  actually exist on those pages — if links cover less than half the
  apparent entries, the TOC is treated as unlinked and every dot-leader
  entry's trailing page number gets its own link. Confirmed necessary in
  practice: GURPS Space ships with a TOC that has *some* links (8) but is
  overwhelmingly unlinked (250 candidate entries) — a hardcoded "0 links
  means unlinked" check would have missed it.
- **The Index** *is* explicitly detected, via a footer/header word match
  (default: "index"), because it needs a different reference grammar (bare
  `Term, 24.` numbers, not `p. NNN`) and applying that grammar to ordinary
  body text would cause massive false-linking of unrelated numbers.
- **Cross-book reference detection has three independent layers**, tried in
  order, each catching a citation style the others miss:
  1. **Trigger word + title span**: a trigger word (auto-detected from the
     PDF's own title metadata — see bug #14 below — falling back to
     `"gurps"`) followed by a run of words that looks like a product title
     stops "GURPS Powers, p. 40" from linking into *this* book's own
     page 40.
  2. **GURPS book-code shorthand**: `p. B123` / `p. MA45` — a short
     all-caps letter code glued directly to the page number is GURPS's own
     formal citation convention for referencing a *different* book (`B` =
     Basic Set, `MA` = Martial Arts, etc.). Any such code is always treated
     as cross-book, regardless of which letter — deliberately not trying to
     detect "this book's own code" and allow self-references through it,
     since a missed same-book link is a much smaller problem than a
     wrongly-linked cross-book one.
  3. **Known-title allowlist for bare italicized citations**: some books
     cite their own parent/related book by name alone, no "GURPS" prefix
     (e.g. "High-Tech, pp. 13-15" inside a High-Tech supplement, since
     repeating "GURPS" would be redundant in context). Matched against a
     small hardcoded list, `KNOWN_GURPS_TITLES` — **not** against "is this
     phrase absent from the book's own vocabulary," which was tried first
     and produced 85 false positives on a single 55-page book (see bug #11
     for why that approach was abandoned).

## Known bugs already found and fixed — do not reintroduce these

Each of these cost real debugging time against the actual book. If you're
rewriting or "cleaning up" any of this logic, re-derive these test cases
first.

1. **`rect.intersects()` is too permissive for "already linked" checks.**
   Adjacent lines' word bounding boxes routinely touch or overlap by a
   fraction of a point (normal line-leading behavior in PyMuPDF's word
   extraction). A plain `intersects()` check treats a reference on one line
   as "already linked" because an *unrelated* reference on the line directly
   above or below happens to share a boundary pixel. This silently dropped
   ~3% of all legitimate links on every run before it was caught. Fixed with
   `rects_meaningfully_overlap()`, which requires >50% area overlap, not
   just a touching edge. **Never revert to plain `intersects()` for this
   check.**

2. **Building a link rect from `words[start].top_left` to
   `words[end].bottom_right` breaks when a reference wraps across a line
   break.** If "Chapter" ends one line and its number starts the next, the
   start word's x0 can be *greater* than the end word's x1, producing an
   inverted rectangle. `fitz.Rect` silently normalizes this into a box
   spanning the full width between both points *and* both lines vertically —
   covering a chunk of unrelated text on both lines. Fixed by grouping the
   reference's words by `(block, line)` and building one rect per line.

3. **PyMuPDF's `get_links()[i]['page']` field is not reliable ground
   truth**, specifically for link annotations authored by third-party tools
   (confirmed with PDF Expert-created links). It can misreport the
   destination page by exactly one, even though the annotation's actual
   `/A /D` destination array — an indirect reference straight to the target
   Page object, which is what every compliant reader (including PyMuPDF's
   own rendering) actually follows — is correct. **When auditing
   correctness, resolve the true target by following `/A/D[0].objgen`
   through the page tree yourself (via `pikepdf`), don't trust the
   convenience API.** This produced a full afternoon of chasing a phantom
   "PDF Expert has an off-by-one bug" before the real cause was found: our
   own verification method was misreading a correct file.

4. **Passing a cached `TextPage` object into `page.search_for(..., 
   textpage=tp)` silently returns zero matches**, even when the text is
   present and a plain `page.search_for(text)` call (no textpage reuse)
   finds it immediately. Don't reuse TextPage objects across `search_for`
   calls as a performance optimization — it isn't needed anyway; the actual
   bottleneck in this pipeline is always `doc.save()`, never per-word text
   lookups.

5. **`doc.save(garbage=3, deflate=True)` can take minutes and can
   *increase* file size** if the source PDF used third-party compression
   (e.g. PDF Squeezer) that PyMuPDF doesn't preserve when fully rewriting
   the file. Since this pipeline only *adds* annotations and never modifies
   existing content streams, use an **incremental save** instead: copy the
   source to the output path, open that copy, make changes, call
   `doc.saveIncr()`. Near-instant, and doesn't touch existing compression.

6. **`pypdf`'s `PdfWriter.append()` silently drops a small number of
   annotations during the copy itself**, independent of anything done to the
   pages afterward (confirmed: link count already short right after
   `append()`, before any cropping/editing). Don't build PDF-editing
   pipelines around `pypdf`'s writer/append pattern if annotation fidelity
   matters. Prefer `pikepdf`, editing the already-open document's page
   objects in place with no copy/append step.

7. **`pypdf` writers drop `/PageLabels` and the `/Info` metadata dict by
   default**, silently. If a script needs to preserve these, it must
   explicitly copy them back in afterward (or better, avoid the pypdf
   writer pattern per #6).

8. **A leading character glued onto a target word breaks exact-string
   matching.** Real examples found in this book: a bullet character joined
   via narrow-no-break-space (`"•\u202fpp.\u202f324-334"` as one PDF
   "word"), a bare paren joined the same way (`"(GURPS"`, `"(Chapter"`).
   Any matcher comparing a token against an expected keyword must strip
   leading non-word characters first (`re.sub(r'^\W+', '', tok)`), not just
   check for one specific expected prefix like `"("`.

9. **A soft hyphen (`\xad`) from a mid-word line-wrap breaks
   `search_for()`.** E.g. "Chapter" rendered as `"Chap\xad"` + `"ter"` across
   a line break. `search_for("Chapter")` finds nothing, because the
   extracted text stream still contains the literal `\xad` character.
   `search_for()`-based refinement is not a valid fallback for this case —
   you need dedicated word-pair detection (check if
   `word[i].rstrip('\xad-') + word[i+1]` reconstructs the target word).

10. **A `search_for()` probe built from only the first number of a range
    truncates the rest of the range.** Fixed a bug where "Chapters 11-13"
    got a link rect stopping right after "11", visually cutting off "-13",
    because the trimming probe only ever searched for `"Chapters 11"`. When
    building a refinement probe for a multi-number reference, try the
    full-range text first (`"Chapters 11-13"`, then the en-dash variant,
    then `"11 and 13"`) before falling back to the single-number form.

11. **Case-insensitive/substring matching against a set of known titles
    produces real false positives — this was tried and abandoned once
    already.** An earlier design linked any *exact-text italicized run*
    matching a chapter title (e.g. linking every italicized "Combat"). This
    matched ordinary prose ("Climbing, Stealth, and Swimming *skills*."),
    character-sheet template labels ("*Advantages:* 15 points chosen
    from..."), and mid-word tokenization artifacts. It was replaced with
    matching the book's own actual, unambiguous cross-reference convention
    (explicit "Chapter N" text) instead of inferring intent from styling.
    **If extending chapter-name-only linking (no explicit "Chapter N"
    wording) in the future, verify each match against real surrounding text
    before trusting an aggregate "N links added" count — a plausible-looking
    number hides false positives easily.**

12. **A long-running background process started with plain `&` gets killed
    when its parent shell session ends** (relevant if running long jobs from
    an agentic/tool-based environment). Use `setsid nohup ... &` to actually
    detach, then poll for completion — confirmed this survives across
    separate tool invocations where plain backgrounding does not.

13. **A PyMuPDF/MuPDF corruption found while building the TOC-hyperlinking
    feature: inserting a large number of links (100+) across multiple
    pages in one session, on pages that previously had a large number of
    REAL links removed via `delete_link()` followed by a full
    `doc.save(garbage=3, deflate=True)` rewrite, can cause `get_links()`
    to return IDENTICAL link lists (same xrefs) for multiple different
    pages when the file is reopened.** Confirmed reproducible:
    `page4.get_links() == page5.get_links()` literally `True`, same xref
    numbers. Isolated testing narrowed this to specifically requiring the
    delete-then-full-rewrite step beforehand; the identical high-density
    multi-page insertion pattern on pages that never had links at all
    (verified via a from-scratch synthetic test PDF, and via pristine
    untouched pages of a real book) works correctly with no corruption.
    This pipeline never calls `delete_link()` anywhere in its own normal
    operation, so this shouldn't be triggerable through ordinary use —
    but if a future feature ever needs to strip and re-add a large batch
    of existing links in one session, re-verify this specifically before
    trusting the result, using the same `page[a].get_links() ==
    page[b].get_links()` identity check that caught it here. **Update:**
    validated against a real never-linked TOC (GURPS Space) with no
    duplication whatsoever — this was confirmed to be an artifact of the
    test methodology (deleting a large batch of real links, not a
    genuinely-never-linked page), not a real-world risk.

14. **The `search_for()` glue-trim refinement (bug #9's fix) was
    originally added only for chapter references, then extended to plain
    `p. NNN` page references — and that extension immediately introduced
    a regression identical in spirit to bug #10.** The refinement probe
    was built from the single page number only (`"p. 10"`), and since
    that's a literal text *prefix* of a range like `"pp. 10-11)"`,
    `search_for` happily matched it — truncating every single range
    reference in the book to just its first number. Same root cause and
    same fix as #10 (try the full range text first), just needed
    reapplying at the new call site. **Lesson that generalizes: when
    copying a fix from one code path to a structurally similar one,
    re-derive whether the ordering/precedence assumptions the original fix
    depended on actually transferred — they silently didn't here.**

15. **A single PDF "word" can have a genuinely broken bounding box
    reported by PyMuPDF itself**, not caused by anything in this
    pipeline's own logic. Found in testing: an image caption's text run
    with an unusual transform matrix produced a word (`"p. 516.)Picture"`)
    whose bbox spanned an entire page column (from PyMuPDF's own
    `get_text("words")` output, not something this code constructed).
    Not fixable at the source. Mitigated with `is_reasonable_link_rect()`
    — a safety net that refuses to insert any link taller than ~3 lines or
    wider than ~90% of the page, applied at every `insert_link` call site.
    Rare (found exactly once across two full books), but the check is
    cheap and worth keeping as defense-in-depth against the next
    never-seen-before anomaly like it, not just this specific one.

16. **Chapter-list references aren't always a single number or a 2-number
    range/pair — GURPS also writes genuine comma-separated lists**, e.g.
    "Chapters 2, 4, and 6". The original chapter-number detection only
    handled `Chapter N` and `Chapters N-M`/`N and M`; a list like this
    would silently link only the first number and drop the rest. Fixed by
    extending detection to walk arbitrary comma/and-separated sequences,
    where each number after the first is its own standalone word token
    and gets linked to its own chapter individually (the first number
    still gets the original combined-rect/line-wrap-safe treatment; only
    the *additional* list members use a simpler individual-word rect).

17. **The "is this italicized phrase part of this book's own vocabulary"
    approach for catching bare (no "GURPS" prefix) other-book citations
    was tried, and abandoned, for the same reason as bug #11 — false
    positives.** Built a vocabulary from the book's own TOC + Index and
    flagged any italicized phrase before a reference that wasn't in it.
    Tested against a real 55-page supplement: 87 flags, ~85 false
    positives — same-book cross-reference headings ("Wet Cell,"
    "Secondary Batteries") that exist in body text as bolded run-in
    headers but aren't fully captured by the formal TOC/Index, so
    "unrecognized" wrongly meant "must be some other book." Replaced with
    a small explicit allowlist of real GURPS product titles
    (`KNOWN_GURPS_TITLES`). Necessarily incomplete, but that's the safe
    failure direction — an unlisted title just falls through as same-book
    (a missed skip) rather than wrongly blocking a real same-book link.
    Result on the same book: 17 flags, all genuine, zero false positives.
    **The general lesson repeated across bugs #11 and #17: "flag anything
    that doesn't match a known-good set" sounds more thorough than "flag
    only a known-bad set," but in practice the known-good set is never as
    complete as it looks, and incompleteness there is silent and harmful —
    while incompleteness in a known-bad allowlist just means an occasional
    missed catch, which is easy to extend later from a real example.**

18. **The cross-book trigger word (bug list item in "Core architecture")
    is auto-detected from the PDF's own `/Info Title` metadata** (first
    non-stopword, e.g. "GURPS High-Tech: Electricity and Electronics" →
    `"gurps"`) rather than hardcoded, specifically so the tool adapts to
    non-GURPS books without editing the script. Falls back to `"gurps"`
    with a printed warning if the PDF has no usable title — that fallback
    will be *wrong* (not just unhelpful) for a non-GURPS book with no
    title metadata, so if cross-book filtering looks broken on a new book,
    check the startup print line for what trigger word was actually used
    before assuming the detection logic itself is at fault.

19. **`detect_page_labels()`'s single-global-offset assumption
    (`pdf_index - printed_number` constant for the whole book) breaks
    completely on a file assembled from two separately-paginated books
    glued together** — confirmed on `combine_gurps_basic_set.py`'s merged
    Characters+Campaigns output. Splicing pages from a second book into
    the middle/end of a first one shifts that offset at every
    insertion/deletion point, so the file actually contains *several*
    valid offsets, not one. `detect_page_labels()` picks whichever one
    wins the majority vote (the larger source book) and treats every page
    number belonging to the other offset as noise, outside the resulting
    `valid_range` — so **every reference anywhere in the book pointing to
    a page in the "losing" book gets silently rejected as "out of page-number
    range."** Measured on the real 575-page combined file: two dominant
    offsets, 324 pages' worth of footer votes for Characters vs. 234 for
    Campaigns — meaning all 234 of Campaigns' pages, and every reference
    to them from anywhere in the book (including from within Characters),
    were being skipped before this was fixed. Not a rounding-error-sized
    bug; it's binary per book. **Fix, scoped to `combine_gurps_basic_set.py` only**
    (deliberately *not* applied to `hyperlink_pdf_universal.py` itself —
    see the "Nothing about page numbering is hardcoded" bullet under
    "Core architecture" above, which this confirms in practice):
    `combine_gurps_basic_set.py` already builds and verifies `combined_labels`, the
    true label for every output page, while constructing the merged file.
    Its own `add_hyperlinks()`
    uses that directly as a `{printed_number: pdf_index}` dict instead of
    re-deriving numbering from footer text under an offset assumption —
    no offset math, no false "out of range" rejections possible. Verified
    against the real merge: page-reference skips for this reason dropped
    from what would have been ~234 pages' worth to 5, and those 5 are all
    independently explainable (4 cite pages 329-334, which the script
    itself deletes as cut content and which therefore genuinely no longer
    exist; 1 cites what's now roman-numeral front matter, the same
    pre-existing limitation noted below). **If this pattern comes up
    again** (any future need to hyperlink a book assembled from multiple
    source PDFs with independent pagination), re-derive this same fix
    rather than reaching for `detect_page_labels()` — or add proper
    piecewise/multi-offset support to that function itself if a
    combined-file scenario ever needs to reuse it directly.

20. **The TOC/Index page-detection heuristic (footer/header word repeated
    on every page of that section) is a GURPS convention, not a universal
    one — confirmed broken outright on real Mongoose Traveller books.**
    `hyperlink_pdf_universal.py`'s `detect_toc_pages()`/`detect_index_pages()`
    look for a keyword like "contents"/"index" appearing in the *footer/
    header band of every page* of that section. Mongoose's books never do
    this — the word appears exactly once, as a one-off page-top heading.
    A literal port would have silently detected zero TOC/Index pages on
    every Mongoose book, quietly disabling chapter extraction *and* the
    TOC self-hyperlinking feature with no error. Fixed in
    `hyperlink_pdf_mongoose.py`'s `page_has_heading()` with two heuristics
    derived from real extracted word data instead: (a) an anomalously
    huge bounding box (>50pt tall) — confirmed on the actual Index-opening
    page of all 3 test books, apparently MuPDF mis-measuring a decorative
    section-title treatment (same anomaly class as bug #15, but a
    reliable *positive* signal here rather than noise to filter out), or
    (b) a normal word that's simply much larger than body text (≥17pt vs.
    ~13pt body) and sits in the top 40% of the page. **If porting either
    detector to another new publisher, don't assume either convention —
    check real footer/header text across several pages first.**

21. **A British-publishing range-abbreviation convention ("pages 152-3"
    meaning 152-153, not literally page "3") will silently produce a
    backwards or nonsensical range if parsed the same way as a normal
    range.** Confirmed in a real Mongoose book (Traveller Companion).
    Fixed with `resolve_range_end()`: only expands the second number when
    it's *both* shorter than the first number's digit count *and*
    numerically smaller than it (an ordinary non-abbreviated range like
    "110-125" never goes backward, so it's left untouched) — keeps the
    first number's leading digits and swaps in the written trailing
    digits (`152` + `3` → `153`).

22. **Mongoose's own cross-book citation convention puts the other book's
    title *after* the page reference** ("page 149 of the Traveller Core
    Rulebook"), the reverse of GURPS's "GURPS `<Title>`, p. NNN" (title
    *before*). The existing backward-looking `title_nearby()` structurally
    cannot catch this — it only ever scans words preceding the reference.
    Fixed by adding a separate forward-looking `title_after()` layer,
    triggered by "of"/"in" (optionally + "the") right after the
    reference, requiring **at least 2** consecutive Title-Case words
    afterward (not just 1) to avoid a false skip on an incidental
    capitalized word like "of the Introduction" — real citations are
    confirmed to always be multi-word product names ("Traveller Core
    Rulebook", "High Guard"). **If a future publisher's convention differs
    from both of these shapes, add another dedicated layer rather than
    trying to generalize `title_nearby()`/`title_after()` into one
    direction-agnostic function** — keeping them separate is what made
    each one's false-positive guard easy to reason about independently.

23. **A PDF's `/Info Title` metadata can't be trusted to exist or be
    usable, even less reliably than assumed when that field was first
    added (bug #18).** Confirmed on real Mongoose PDFs: Core Rulebook and
    Companion both have a blank title, and High Guard's title is a literal
    leftover InDesign export filename (`"High Guard Cover.indd"`) — using
    its first word ("high") as the cross-book trigger would have been
    actively wrong, not just unhelpful. Fixed in two parts: (a)
    `detect_title_trigger_word()` now first checks whether the title
    string itself is shaped like a filename (`re.search(r"\.\w{2,5}$",
    title)`) and discards it if so, same as an empty title; (b) when no
    usable title survives, it falls back to scanning the first 6 pages'
    extracted text for a capitalized word immediately before a `©`/`(c)`
    copyright mark (e.g. "Traveller ©2026 Mongoose Publishing Ltd." →
    `"traveller"`) instead of giving up and using the hardcoded `"gurps"`
    default, which would silently disable cross-book filtering entirely
    on a non-GURPS book with no title metadata.

24. **A decorative letter-spaced chapter-divider graphic can bleed
    single-letter "words" into forward-scanning text logic, corrupting a
    title match.** Found via `title_after()` on a real page (*Aliens of
    Charted Space*): a section divider rendered as "HIGH GUARD:
    ASLAN\nC\nH\nA\nP\nT\nE\nR..." extracts as a run of individual
    single-letter word tokens immediately following a genuine title.
    Without a guard, the collected title text would trail off into
    "Aslan C H A P T" instead of stopping at the real title. Fixed by
    rejecting any token shorter than 2 characters (or not starting with
    an uppercase letter) as a stop condition in `title_after()`'s
    word-collection loop, rather than only checking for line breaks or
    punctuation.

25. **The `p.`/`pp.` abbreviation-only reference grammar really is
    GURPS-specific, confirmed rather than just suspected** (this was
    flagged as an open question in "Known open limitations" before real
    non-GURPS testing happened). Mongoose's Traveller line spells the
    word out in full ("page 149", "pages 152-3") instead of abbreviating
    it. `hyperlink_pdf_mongoose.py` adds `page`/`pages` as an equally
    valid keyword alongside `p.`/`pp.` throughout — both the initial
    reference-matching pass and the `search_for()` glue-trim refinement
    probes (bug #14) needed their own "page"/"pages" probe variants,
    since a probe string built for the abbreviated form (`"p. 10"`)
    never matches spelled-out source text and would silently fail the
    refinement step, falling back to the coarser word-token rect instead.

26. **Bugs #22's two directional layers (`title_nearby()` backward,
    `title_after()` forward) still don't cover every citation shape in
    the wild — confirmed against a different Mongoose product, the
    2300AD boxed set (Book 1: Characters & Equipment, Book 2: The
    Worlds of 2300AD, Book 3: Vehicles & Spacecraft), not the books
    bug #20-#25 were built against.** Real examples found: `"(see
    Characters & Equipment page 38)"` and `"in Book2 page 23"` — a bare
    `<Title> page NN` citation with **no trigger word and no connector
    at all** before the title. `title_nearby()` requires a trigger word
    immediately before the title span; `title_after()` requires
    `"of"/"in"` immediately *after* the page number. Neither fires here.
    Fixed with two more dedicated layers, per bug #22's own advice to
    add another layer rather than generalizing the existing ones:
    - `title_bare_before()`: same lookback-and-grow shape as
      `italic_title_nearby()`, but keyed on a known-title allowlist
      (`KNOWN_TRAVELLER_TITLES`) instead of italic styling, since there's
      no reliable style cue for this citation shape at all. Initially
      missed "Characters & Equipment" entirely — the `&` isn't
      Title-Case, so the backward-growing word loop stopped dead on it
      before ever reaching "Characters". Fixed by letting a
      `TITLE_CONNECTORS` word (already used by `looks_like_title_span()`)
      pass through the loop without ending it, the same accommodation
      that function already makes for a forward-scanned title span.
    - `book_n_nearby()`: this boxed set's own internal shorthand for
      citing a *sibling* PDF in the same product (`"Book2"` immediately
      before `"page NN"`, meaning Book 2's own page 23 — which doesn't
      exist in this file at all). Always cross-book regardless of which
      number, mirroring `BOOK_CODE_TOKEN`'s existing "any code counts"
      design (bug list under "Core architecture").
    **General lesson, now confirmed twice (bugs #20/#22 vs. this one):
    testing against one or two real books in a product line is not the
    same as testing against the whole line — a different book (or in
    this case, a different sub-product from the same publisher) can use
    a citation grammar the earlier testing never exercised.** Don't
    treat "verified against real Mongoose books" as "verified against
    every Mongoose book" — ask which specific books were tested before
    assuming a convention is covered.

27. **The title-metadata-fallback regex from bug #23 can match INTO the
    middle of a glued alphanumeric brand name, not just skip it.**
    `detect_title_trigger_word()`'s fallback scans for a capitalized word
    immediately before a `©`/`(c)` mark. Confirmed on all three 2300AD
    boxed-set books, whose copyright line reads `"2300AD ©2021 Mongoose
    Publishing"`: the original pattern (`r"([A-Z][A-Za-z']+)\s*(?:©|\(c\))"`)
    has no anchor forcing the captured span to start at a real word
    boundary, so it happily matched starting mid-token, inside "2300AD",
    capturing just `"AD"` — a meaningless two-letter trigger word, not an
    error, so nothing about the run looked wrong (same failure class as
    bug #8: silent, plausible-looking, wrong). Fixed by (a) adding a
    `\b` anchor so the match can't start inside a word, and (b) allowing
    a leading digit in the captured class, since the *correct* answer
    here is genuinely alphanumeric ("2300ad", this product line's own
    self-brand — not "traveller", which is the separate underlying
    rules-engine brand and doesn't appear where these books cite each
    other). Confirmed the fix has real effect, not just a more sensible
    printed trigger word: re-running against the actual PDFs with the
    fix applied, `title_nearby()` correctly catches several genuine
    "2300AD, page NN" cross-references in Book 1's CSV report (visible
    as `skipped -- other-book title nearby: 2300AD`) that a trigger word
    of literal `"ad"` could never have matched. (The *aggregate*
    skip-title count for that book happened to come out identical
    before and after this fix — the pre-fix report wasn't kept to
    determine which specific citations were being caught instead, so
    that coincidence is unexplained; it doesn't change that the
    post-fix behavior is independently confirmed correct.)

28. **Mongoose's 1st-edition "numbered series" line (Book 1: Mercenary,
    Book 9: Robot, Book 10: Cosmopolite, Alien Module 1: Aslan, ...) puts
    a generic structural word + volume number BEFORE the real title in
    `/Info Title`, and the trigger-word extraction had no idea to skip
    it.** Confirmed real metadata: `"Book 9: Robot"`,
    `"Book 1: Mercenary Second Edition"`, `"Alien Module 1: Aslan"`.
    Taking the first non-stopword picked `"book"` for three different
    books — a common English word, and specifically NOT this line's own
    convention (compare bug #27: there, the *correct* answer was the
    product's own alphanumeric self-brand; here it's the word after the
    colon). No false-positive skip was actually observed from this in
    the three affected books — `title_nearby()` (the only mechanism that
    uses the trigger word) never happened to fire in them — but it's the
    same "silently wrong, technically harmless so far" class of bug as
    #27, not something to leave sitting around waiting for the book that
    does trip it. Fixed by stripping a leading `"<Word(s)> N: "` prefix
    (`re.sub(r"^\s*(?:[A-Za-z]+\s+){1,3}?\d+\s*:\s*", "", title)`) before
    the normal extraction runs. Verified against real titles: correctly
    strips `"Book 9: "` → `"Robot"`, `"Alien Module 1: "` → `"Aslan"`,
    while leaving titles with no such prefix (`"Alpha Crucis Sector"`,
    `"LBB9: Library Data"` — the latter's leading token is one
    alphanumeric word, not `word + number`, so it doesn't match) alone.

29. **`title_after()` and `title_nearby()` had no way to tell "this
    Title-Case phrase names a different book" from "this Title-Case
    phrase is this book's OWN chapter, and the trigger word/connector
    just happens to precede it" — confirmed as a real, not theoretical,
    false-positive source.** Found on *Alien Module 2: Vargr*, whose own
    Contents page lists chapters literally titled "Vargr Character
    Generation" and "Vargr Race": body text like `"page 32 of the Vargr
    Race chapter"` is a SAME-book reference to its own chapter, but
    `title_after()`'s shape-only check (`"of the"` + 2+ Title-Case words)
    can't distinguish that from a real citation of a different product,
    so every one of these was being wrongly skipped as cross-book —
    6 lost same-book links in this one file alone, plus a 7th of the
    same shape in the 1e Core Rulebook. This is exactly the problem
    `italic_title_nearby()` already solves for its own citation shape,
    via the `same_book_vocab` (this book's own TOC+Index terms) built in
    `build_same_book_vocabulary()` — `title_after()`/`title_nearby()`
    just never received it. Fixed by threading `same_book_vocab` through
    both as a `vocab` parameter and checking
    `normalize_title(matched_phrase) in vocab` before treating a match as
    cross-book. Verified with a real before/after re-run: Vargr's added
    count rose 176 → 182 (exactly the 6 recovered links, confirmed by
    diffing the skip reasons, not just the aggregate number), the 1e Core
    Rulebook rose 837 → 838, and all 17 other already-verified books
    (2300AD, 2e, and the rest of 1e) produced byte-identical counts —
    confirming the fix is precisely targeted, not a broader behavior
    change in disguise. **General lesson, extending bug #26's: a
    same-book-vocabulary guard needs to be threaded through *every*
    shape-based cross-book detector, not just the one it was originally
    built for — each new detector added for a new citation shape
    inherits this same blind spot by default and needs the same guard
    explicitly re-applied, it doesn't come for free.**

30. **`page_has_heading()`'s two font-size-based signals (bug #20) don't
    generalize to every Mongoose book — confirmed on a book from a
    different sub-line, *Aliens of Charted Space* vol. 2.** Its
    "CONTENTS" heading is only 14.7pt tall, under signal (b)'s 17pt
    cutoff (tuned on the Core Rulebook/High Guard/Companion set, whose
    headings run ~19-21pt) and nowhere near signal (a)'s >50pt anomaly
    threshold either. Result: `toc_pages` came up empty, and because
    `same_book_vocab` is built *from* TOC+Index pages, that came up
    empty too (`"Built same-book vocabulary: 0 terms"`) — silently
    disabling bug #29's just-added self-citation guard for this entire
    book, not just the TOC self-linking feature. No wrong link was
    actually observed from this in this book's specific 6 skips (all
    genuinely cited other products), but that's luck, not protection —
    a future citation phrased as "of the `<this book's own chapter>`"
    would have been wrongly skipped with zero vocabulary to catch it.
    Fixed by adding a **third**, independent signal (c) to
    `page_has_heading()`: the same keyword rendered *twice* at
    byte-identical bounding-box coordinates on the page — a faux-bold
    rendering trick this book uses for its heading instead of a
    genuinely larger font (confirmed: both "CONTENTS" words share the
    exact same `(x0, y0, x1, y1)`). This needed no size cutoff at all,
    because ordinary body text is never rendered twice at the identical
    pixel position — ruling out the false-positive risk a *lower* size
    threshold would have carried into other books' legitimately-smaller
    subheadings. Confirmed this doubling pattern is real but NOT
    universal (a known-working book, the 2022 Core Rulebook update, has
    no duplication at all — its heading passes via signal (b) normally)
    — so signal (c) is additive, not a replacement, consistent with how
    (a) and (b) already coexist. Verified with a full 21-book regression
    run after the fix: the 2 Aliens volumes now correctly detect their
    TOC/vocabulary, and all 19 other already-verified books (2300AD, 2e,
    1e) produced **byte-identical** added/skipped counts to before —
    confirming signal (c) adds exactly the one detection it was meant to
    and nothing else.

31. **The prose-shaped cross-book checks (`book_n_nearby()`, `title_nearby()`,
    `title_after()`, `title_bare_before()`, `italic_title_nearby()`) were
    being applied to Index-page bare-number entries too, even though an
    Index entry (`"Term \n Number"`) has no real sentence around it for
    those checks to test.** Confirmed a real false positive from this,
    not just a theoretical risk: in the 1e Core Rulebook's own Index,
    the entry `"Travel Codes 180"` sits immediately after the unrelated
    alphabetically-prior entry `"Traveller 2"` — which happens to be
    this exact book's own auto-detected trigger word (bug #23/#27).
    `title_nearby()` matched `"Traveller ... Travel Codes"` as if it
    were a genuine `"<trigger> <title>"` citation, purely from
    coincidental index-list adjacency, and wrongly skipped a real
    same-book Index link. Searched all 21 already-verified books'
    reports for the same pattern (any `"other-book title nearby"` skip
    whose page is a detected Index page) and found exactly this one
    instance — narrow, but not zero, and the underlying category error
    (testing prose grammar against an alphabetized term list) applies
    equally to any future book's Index. Fixed by tracking which entries
    in `all_refs` came from `find_index_references()` vs.
    `find_body_references()` and skipping all five prose-shaped checks
    for the index-origin ones — `book_code` (GURPS-style shorthand) is
    unaffected, since it only inspects the reference's own number token,
    not surrounding words, so it's not vulnerable to the same adjacency
    coincidence. Verified with a full 21-book regression run: the 1e
    Core Rulebook gained exactly the 1 recovered link (838 → 839, skips
    1 → 0) and all 20 other books produced byte-identical counts: a
    second follow-up full-report scan afterward confirmed zero remaining
    "skip on an Index page" instances anywhere. **This is the same
    "narrow but real, not zero" finding pattern as bugs #26/#29/#30 —
    found by deliberately auditing every skip reason across every book
    for a specific suspicious pattern (self-citation, Index-page
    coincidence) rather than only checking the counts looked plausible.**

32. **The first confirmed actual WRONG link found in this whole line of
    testing (bugs #26/#29/#31 were all missed/wrongly-skipped links --
    a link that should exist but doesn't; this one is a link that exists
    and points to the wrong place), and the most serious class of bug
    for that reason.** `title_bare_before()`'s allowlist match required
    the known title to sit *immediately* before the reference, with only
    `"("`, `"see"`, `"cf."`, `"in"` skippable in between. Real Mongoose
    text also uses `"<Title> on page NN"` (`"...the manipulator options
    present in the Vehicle Handbook on page 59"`), which that skip-word
    set didn't cover — `"on"` isn't in it, so the check gave up at "on"
    and never reached "Vehicle Handbook" at all. Confirmed the actual
    consequence, not just the gap: Robot Handbook's report showed this
    exact citation as `"added"`, linking to Robot Handbook's *own* page
    60 — actively wrong, not merely incomplete, since a reader clicking
    it lands on unrelated content in the wrong book entirely. Found by
    auditing "out of page-number range" skips across all 21 books (a
    category not otherwise reviewed this pass) and noticing one, in
    *World Builder's Handbook*, that read `"...found in the Traveller
    Core Rulebook on page 260"` — a real cross-book citation that
    happened to fail silently *for the right final answer, wrong
    reason* (260 exceeds that book's own page count, so it got rejected
    by the range check regardless of whether cross-book detection
    caught it) — which is what prompted searching for how common the
    `"<Title> on page NN"` shape actually is across the corpus. Fixed by
    adding `"on"` to `title_bare_before()`'s skip-word set. Safe to skip
    unconditionally rather than only after a partial title match,
    because the allowlist check is what actually gates a result, not the
    skip-word set — confirmed with a direct test: `"installation on
    vehicles on page 59"` (a real same-book sentence from the very same
    book) still correctly returns no match, since skipping "on" just
    lets the grown phrase reach as far back as a real title exists to
    find, and "vehicles" (lowercase) stops the growth immediately with
    nothing gained. Verified with a full 21-book regression: Robot
    Handbook's added count dropped by exactly 3 (51 → 48, all three
    confirmed genuine "Vehicle Handbook"/"High Guard" citations by
    reading their actual sentences), World Builder's Handbook's dropped
    by 2 with the previously-misfiled "out of range" case now correctly
    bucketed as a title-nearby skip, and every other book's counts were
    unchanged. A follow-up 258-link `pikepdf` destination sweep plus an
    oversized-rect sweep across all 21 outputs came back completely
    clean. **General lesson: an "out of range" skip is not automatically
    a non-issue just because the final outcome (no link added) matches
    what a correct cross-book detection would have produced — the wrong
    mechanism catching it by coincidence is itself a signal that a real
    detection gap exists nearby, worth chasing even when nothing looks
    broken on the surface.**

33. **A source PDF can render an entire body-text line TWICE at
    near-identical coordinates for a bold/shadow visual effect (same
    duplication trick as bug #30's heading fix, just applied to
    ordinary text instead of a heading) — and this caused a genuine
    duplicate-link insertion, not just a missed one.** Confirmed on a
    real page (1e Core Rulebook p.141): `"pages 165–166"` exists as two
    separate PyMuPDF word objects 0.17pt apart at the identical y0,
    because the whole surrounding line is duplicated. Both are within
    the `search_for()` refinement's 2pt y0 tolerance of BOTH duplicate
    occurrences, so `near[0]` — an arbitrary first pick from whatever
    `search_for()` returns, not tied to which of the two original words
    triggered the search — resolved to the *same* final rect for both,
    producing two literal, fully-overlapping `LINK_GOTO` annotations
    stacked on each other pointing at the same target. The existing
    "already linked" check only ran *before* this refinement step,
    comparing each reference's own original (pre-refinement) rect —
    it never re-checked the rect actually being inserted, so this
    post-refinement collision slipped through untouched. Found by
    sweeping every output PDF for pairs of `LINK_GOTO` annotations on
    the same page with >50% rect overlap — a check not run in any prior
    pass — and getting exactly 2 hits, both in the same file. Fixed by
    adding a second `rects_meaningfully_overlap()` check immediately
    before `page.insert_link()`, against the final (possibly refined)
    rect rather than the original one. Verified with a full 21-book
    regression: the 1e Core Rulebook's added count dropped by exactly 2
    (839 → 837, "already linked" skips rose 0 → 2, both now correctly
    the second half of each duplicate pair) and all 20 other books
    produced byte-identical counts. A follow-up sweep confirmed zero
    remaining overlapping-link pairs anywhere, and a 258-link `pikepdf`
    destination re-check plus oversized-rect sweep came back clean.
    **General lesson, complementing bug #30's: this same
    duplicate-rendering trick can appear on *any* text, not just
    headings — any code that assumes "this text appears exactly once on
    the page" (search_for() included) needs to tolerate it, not just
    the heading-detection heuristic that first surfaced it.**

34. **`title_after()`'s title-word loop rejected any word starting with a
    digit, even though the other two title detectors it structurally
    parallels — `looks_like_title_span()` (used by `title_nearby()`) and
    `title_bare_before()` — already allow one.** 2300AD's own product
    titles literally start with "2300AD" (a digit, not a capital
    letter), and `title_after()` never got the same accommodation those
    other two received when bug #26 first added 2300AD support. Confirmed
    via real text in Tools for Frontier Living: `"...found on page 188 of
    the 2300AD Core Rulebook."` should be caught by the "of the `<Title>`"
    pattern `title_after()` exists specifically to catch, but wasn't —
    `bare[0].isupper()` is `False` for `"2300AD"`, so the loop broke on
    step 0, `title_words` stayed empty, and the function returned `None`.
    This particular instance only avoided producing a wrong link by luck:
    page 188 also happens to exceed Tools for Frontier Living's own valid
    range (2-174), so the separate out-of-range check caught it instead —
    same "safety net masking a real detection gap" pattern flagged as a
    concern in bug #32's own general lesson. Searching for other citations
    of the same underlying shape (a digit-led sub-token anywhere inside an
    otherwise-valid title span, not just as the very first word) found a
    second instance in Mercenary that the safety net did **not** catch:
    `"...the Cargo Loader found on page 59 of Supplement 5-6: The Vehicle
    Handbook."` — Mercenary's own valid range is 2-131, and 59 falls
    inside it, so before this fix that citation was genuinely being
    linked into Mercenary's *own* page 59, a second confirmed actual wrong
    link (same severity class as bug #32's first one), not merely a
    masked risk. Fixed by widening `title_after()`'s per-word check from
    `bare[0].isupper()` to `bare[0].isupper() or bare[0].isdigit()`,
    matching the other two detectors exactly. Verified with a full
    21-book regression: Tools for Frontier Living's "page 188" reference
    now correctly reports `skipped -- other-book title nearby: of the
    2300AD Core Rulebook`; Mercenary's added count dropped by exactly 1
    (31 → 30, title-nearby skips 19 → 20) for the `Supplement 5-6` catch;
    all 19 other books produced unchanged counts (Robot Handbook's
    already-established post-bug-#32 count of 48 added / 14 skipped was
    re-confirmed unchanged, not a new regression — an earlier stale
    background-task log being read at the start of this round briefly
    suggested otherwise, before re-deriving which of the two conflicting
    logs actually predated the bug #32 fix). A follow-up `pikepdf`
    destination check across all 21 outputs came back clean: 2430 links
    checked, 0 mismatches, 0 oversized rects, 0 duplicate/overlapping
    rects. **General lesson: when a shape-based accommodation is added
    for one specific citation style to one detector (bug #26 adding
    digit-leading-word support to `looks_like_title_span()` and
    `title_bare_before()` for 2300AD), audit every other detector that
    shares the same "consecutive Title-Case word" shape assumption, not
    just the one the motivating example happened to exercise — and when a
    masked gap surfaces (an "out of range" skip whose citation shape
    looks like it should have been caught by title detection instead, per
    bug #32's own lesson), search specifically for a second, unmasked
    instance of the same root cause before assuming the masked case was
    the only real consequence.**

35. **`KNOWN_GURPS_TITLES` (used only by `italic_title_nearby()`) was
    copied wholesale from the parent GURPS script without removing an
    entry that's actively wrong for this fork: `"traveller"`.** In the
    GURPS codebase that entry means the unrelated 1990s "GURPS Traveller"
    crossover supplement — a real other-book citation there. In
    `hyperlink_pdf_mongoose.py`, every single book in the entire test
    corpus *is* Traveller, so an italicized "Traveller" sitting right
    before a page reference would be a same-book self-reference (e.g. a
    stylistic mention of the game's own name), and this allowlist entry
    would have wrongly flagged it as citing a different product — the
    same shape of self-citation false positive bug #29 already fixed for
    `title_after()`/`title_nearby()`, just via a different detector.
    Never actually observed to fire (confirmed: grepping "italicized
    other-book title nearby" across every CSV report in the full 21-book
    corpus returns zero rows), and not for lack of opportunity — italics
    are common in this corpus (confirmed: 161 italic spans in a single
    sample book), so the mechanism that could reach this entry is
    genuinely active, it just hasn't happened to land on the word
    "Traveller" in any of the 21 books tested so far. Same "silently
    wrong, technically harmless so far" class as bug #28 — not something
    to leave sitting around waiting for the book that does trip it. Fixed
    by removing `"traveller"` from `KNOWN_GURPS_TITLES`. Verified with a
    full 21-book regression: byte-identical added/skipped counts to the
    pre-fix baseline in every single book, exactly as expected for
    removing an entry that had never matched anything. Also fixed a
    verification-tooling gap found while chasing this down: an ad-hoc
    pikepdf destination-resolution script written for this round's audit
    only checked `annot_obj.A.D[0]` and treated every link using the
    equally-valid direct-`/Dest` annotation form (no `/A` action wrapper
    at all — confirmed on native pre-existing links, e.g. a cover-page
    link in Aliens of Charted Space) as a "mismatch," producing 132 false
    alarms on the first run of the widened check. Not a pipeline bug —
    `hyperlink_pdf_mongoose.py` itself never authors that form, and
    `page.get_links()`'s own annotations weren't affected — but worth
    recording since it's the same root lesson as bug #3 taken one step
    further: **ground-truth destination verification needs to handle
    *both* legal PDF destination encodings (`/A/D` and bare `/Dest`), not
    just the one path a particular PDF producer happens to use.** Also
    used this round's regression to close out an open question about
    `find_chapter_number_refs()`: a real `"Chapter 21"` citation exists in
    *The Worlds of 2300AD* (Book 2 of the 2300AD boxed set) but correctly
    produces no link, confirmed NOT a detection bug — that book has zero
    `"Contents"` text anywhere at all (a direct full-text search across
    every page came back empty), so `chapter_by_number` is legitimately
    empty and there is no page to resolve chapter 21 to, the same
    "genuinely nothing to link" conclusion already reached for two 1e
    books with zero page citations at all.

36. **A targeted security audit (not a real-book test round like every
    other entry here, but the same "verify, don't assume" standard)
    found two real gaps in how the pipeline treats an untrusted input
    file, plus confirmed the rest of the script has a small attack
    surface.** No `eval`/`exec`/`os.system`/`subprocess`/`pickle`/
    network calls anywhere, no hardcoded secrets, and every regex uses
    bounded quantifiers (`{1,4}` max, capped outer groups) -- no ReDoS
    risk. Two concrete gaps fixed:
    - **CSV/formula injection in the `_link_report.csv` output.** The
      "Matched Text" and "Detail" columns are built directly from
      PDF-extracted text -- untrusted if the source PDF itself is (e.g.
      a PDF someone else handed you, not one of your own known-good
      books). A cell beginning with `=`, `+`, `-`, `@`, tab, or carriage
      return is interpreted as a formula by Excel/Sheets when the report
      is opened there (OWASP's well-known "CSV Injection" class) --
      unescaped, this could let a maliciously-authored PDF's own body
      text execute as a spreadsheet formula once someone opens the
      generated report. Fixed with `csv_safe()`, applied to every field
      before writing: prefixes a literal quote onto any string starting
      with one of those characters, which Excel/Sheets/Python's own
      `csv` reader all treat as forcing plain-text interpretation
      without changing what a human reader sees. Verified harmless on
      real data: unit-tested against real formula-trigger strings (all
      correctly quoted) and plain reference text like `"Chapters 2, 4,
      and 6"` (passed through unchanged), then a full 21-book regression
      confirmed byte-identical added/skipped counts and zero rows in any
      output CSV starting with a stray quote.
    - **Symlink traversal in `--batch --recursive`.** `Path.rglob()`
      follows symlinks by default on Python versions before 3.13's
      `recurse_symlinks` option existed (and even where a symlinked
      *directory* is no longer followed, a symlinked *.pdf file* sitting
      directly in the input directory still resolves straight through
      `is_file()` regardless of Python version -- confirmed by direct
      test). If `in_dir` came from an untrusted source (e.g. an
      extracted third-party archive) and contained a symlink pointing
      outside itself, the batch would silently process a file outside
      the intended directory and mirror it into the output tree. Fixed
      by resolving each candidate path and skipping (with a printed
      warning) any whose real path lands outside `in_dir`'s own resolved
      root. Verified with a synthetic test: a symlinked `.pdf` pointing
      to a file outside `in_dir` was correctly skipped with the warning
      printed, while a legitimate PDF in the same directory was still
      found and processed normally.
    Noted but not changed, since neither is a flaw introduced by this
    script's own logic: (1) resource limits against an adversarially
    crafted PDF (huge page count, pathological word count) don't exist
    here, but the actual attack surface for that is PyMuPDF/MuPDF's own
    C parser, not this script's Python logic; (2) `doc.saveIncr()` (bug
    #5's deliberate choice) preserves whatever prior revision history
    already exists in the source PDF's bytes rather than stripping it --
    relevant only if a user's threat model requires prior redacted/
    deleted content to be unrecoverable, which was never a stated
    requirement for this pipeline.

37. **`KNOWN_TRAVELLER_TITLES` had every full compound title ("Traveller
    Core Rulebook", "Traveller Core Book") but no bare "Core Rulebook"
    entry -- a real, separate citation shape confirmed in TWO different
    sub-lines, both producing actual wrong same-book links before the
    fix.** Found by re-auditing every "added" (same-book) page-reference
    link across the whole 21-book corpus for one immediately before it
    that looks like a 2+-word Title-Case phrase -- the same audit
    approach that caught bug #34's Mercenary wrong link, just run
    exhaustively this time instead of stopping at the first hit. (Two
    false leads had to be ruled out first: a naive first pass flagged
    dozens of hits that turned out to be same-book section/glossary
    cross-references this book already correctly self-links, like "See
    Space Combat, page 146" inside the Core Rulebook citing its own
    chapter; and the scan script itself had a real bug -- using
    `list.index()` to relocate each CSV row's reference in the page's
    word list always finds the *first* matching token on the page,
    silently misattributing context on any page with more than one
    "page N" citation, which produced a phantom "Traveller Core
    Rulebook" false alarm on a citation that had nothing to do with it.
    Fixed by tracking a per-page cursor that advances past every
    reference in document order, not just the flagged ones.) Two
    confirmed real wrong links once the scan was trustworthy: Aliens of
    Charted Space p.139 ("roll on the Injury table of the Core Rulebook
    (page 47)") and p.272 ("...Mishap Table of the Core Rulebook (page
    24)") were both being linked into this book's own pages 47/24
    instead of recognized as citing the (separate, not-in-corpus) core
    rulebook -- confirmed via `title_bare_before()`'s own trace: it
    correctly walks backward through "the"/"in"/a digit-led "2300AD" (all
    allowed to pass through per bugs #26/#34's fixes) and builds up
    exactly the right phrase, but neither "core rulebook" alone nor the
    brand-prefixed combination was ever on the list, so it had nothing to
    match against and fell through as same-book at every step. A third
    real citation, Tools for Frontier Living p.21 ("...the Organisations
    chapter in the 2300AD Core Rulebook, (page 83)"), was being linked
    the same way. Fixed by adding a bare `"core rulebook"` entry.
    Confirmed safe before adding it: neither actual Core Rulebook PDF (1e
    or 2e) mentions "Core Rulebook" adjacent to a page number anywhere in
    its own text at all (both real self-mentions are cover-page/foreword
    prose with no reference nearby), so this can't cause a same-book
    self-citation to be wrongly skipped in the one place that would
    actually matter. Verified with a full 21-book regression: Aliens of
    Charted Space's added count dropped by exactly 2 (60 → 58, title-skips
    31 → 33) and Tools for Frontier Living's dropped by exactly 1 (1 → 0,
    title-skips 5 → 6) -- both books' *only* changes, matching the three
    citations found -- and all 19 other books produced byte-identical
    counts. A follow-up `pikepdf` destination + oversized/duplicate-rect
    sweep came back clean: 2427 links checked (3 fewer than the prior
    run, matching the 3 flipped references), 0 mismatches, 0 oversized,
    0 duplicate/overlapping. **General lesson: an allowlist built from
    the citations seen in the FIRST few books tested will keep missing
    real citations in later books that abbreviate the same title
    differently -- re-run the "added link preceded by a Title-Case
    phrase" audit periodically as more books get tested, the same way
    bug #34 did once, rather than treating the allowlist as finished
    after its first pass.**

38. **The first *external contribution* to this codebase (GitHub PR #1,
    from a real other contributor, not written or tested from inside
    this project's own dev loop) added an alternative to
    `detect_page_labels()`'s single-global-offset assumption (see the
    "Nothing about page numbering is hardcoded" bullet above, and bug
    #19): when a PDF carries its own `/PageLabels` and they're
    trustworthy, build a direct `printed_number -> pdf_index` dict from
    them instead of voting on one offset for the whole book. This is the
    generalized version of the fix bug #19 built one-off, inline, for
    `combine_gurps_basic_set.py` alone — motivated by the same underlying
    problem (a file assembled from more than one independently-paginated
    source), just for any PDF that happens to ship with correct labels
    already, not only that one script's own merge output. "Trustworthy"
    is a whole-book check: the labels have to agree with the real footer
    numbers on at least half of all observed pages (`footer_observations()`,
    factored out of `detect_page_labels()` so both the vote and this
    agreement check share one scan) — a PDF whose labels are just the
    default physical numbering (confirmed on GURPS Magic: 0/241 agreement,
    correctly falls back to the footer vote) would otherwise put every
    link a couple of pages off.

    **Reviewed the same way any of this project's own changes are** — not
    taken on the PR's own reported numbers alone: ran both the unpatched
    script and the PR's branch against 4 real GURPS 4E books (Characters,
    Campaigns, High-Tech, Basic Set Fourth Edition Revised) and diffed
    every row of the CSV report, not just the summary counts. Found a
    real, confirmed regression, not a theoretical one: Characters and
    Campaigns share a boilerplate sentence ("...the pages are sequentially
    numbered; Book 2 starts on p. 337.") explaining that their combined
    index spans both books. In the *Characters* file specifically,
    `/PageLabels` labels its trailing Warehouse 23 ad page "337" — Steve
    Jackson Games' distributor apparently continues the boxed set's
    overall page count into the ad insert even though the real "Book 2"
    content is a different PDF entirely — and the PR's label lookup
    trusted that match unconditionally, linking "p. 337" straight to the
    ad page instead of leaving it correctly unresolved (as the unpatched
    footer vote already did). A second, quieter side effect surfaced the
    same way: High-Tech's own Index has entries like `"Mk 1, 130, 137."`
    and `"S&W Number 1, 94."` — weapon model names ending in a bare "1"
    that word-tokenization already misreads as its own citation number (a
    pre-existing ambiguity, not something this PR introduced) — which the
    unpatched footer vote never surfaces as a link because it never
    establishes page 1 (the credits page, no footer number at all) as a
    valid target in the first place. The PR's label lookup does reach
    page 1, so these previously-silently-skipped mis-parses became real,
    wrong links to the credits page.

    **Root cause, in both cases: the whole-book agreement check says the
    labels are trustworthy in aggregate, but says nothing about any one
    specific label entry** — an individual `/PageLabels` entry can exist
    on a page with no printed folio at all (a title/credits page counted
    as the nominal start of a numbering run, or, as in the Characters
    case, a back-matter page whose label has nothing to do with that
    volume's real content). Fixed by keeping only the label entries whose
    *target page's own footer* directly confirms that same number —
    `{n: i for n, i in label_to_index.items() if (i, n) in obs_set}` —
    so an unconfirmed number now falls through to "out of range" exactly
    like it already did before this lookup path existed, rather than
    resolving via a label with nothing backing it. Verified with a full
    re-run of all 4 books: every one of the 4 previously-added links this
    uncovered is now correctly skipped again, and a complete row-by-row
    CSV diff against the pre-PR baseline shows **zero** remaining
    differences across all four files — this restores the exact prior
    safe behavior for every single-volume book tested while leaving the
    label-based lookup fully intact for whatever real multi-offset
    combined file motivated the PR in the first place.

    The fix was posted as a PR review comment first (with the full diff
    and verification results), then, once the contributor agreed with the
    reasoning, pushed directly onto the contributor's own branch (GitHub's
    "allow edits from maintainers" setting, enabled on this PR) rather
    than merged unmodified and fixed up afterward — keeping the
    contributor's own commit history intact and the fix visible as part
    of their PR rather than a follow-up patch. That push initially failed
    with a permission error under the GitHub identity the working
    environment happened to be authenticated as at the time; it succeeded
    once the correct account (`plazman30`, the actual maintainer of this
    repo) was logged in instead — worth remembering that "maintainer can
    modify" is enforced per-account, not per-repository-URL: a remote URL
    that *names* an account (`https://plazman30@github.com/...`) doesn't
    make git or `gh` actually authenticate as that account; only the
    credential/token actually logged in does, and pushing to a
    contributor's fork specifically will fail silently-until-attempted if
    those two don't match. The contributor independently diffed the
    pushed commit against the posted patch (confirmed identical) before
    approving. **General lesson, extending bug #19's own: a fix that
    generalizes a known limitation (single-offset assumption) to more
    cases than the original one-off workaround covered is still worth the
    same real-book regression testing as any other change to this
    matching logic — a more general mechanism has more surface area for
    exactly this class of "technically-present-but-unconfirmed metadata"
    bug to hide in, not less.**

## Testing / verification methodology

- **Don't trust `page.get_links()[i]['page']` as ground truth** (see bug #3
  above). For a trustworthy audit, resolve the real destination via
  `pikepdf`: find the link annotation by xref, read `/A/D[0]`, and match its
  `objgen` against the document's page list.
- **A "does the visible reference number match the target page's printed
  footer" check will produce false alarms on range/wrap-continuation
  entries.** E.g. for "320-321" wrapped across a line as two link rects, the
  second rect's visible text is "321" but it correctly targets the page
  whose footer says "320" (the range's start). Don't treat every mismatch
  here as a bug without checking whether it's a continuation piece first.
- Good general practice established over many rounds of this: after any
  change, (1) run on a **fresh, unlinked copy** of the source file, not on
  an already-linked test file (existing links can mask a bug in the code
  that was supposed to create them), (2) spot-check a random sample of
  ~150-200 links against real footer text, (3) sweep the whole document for
  any suspiciously large link rects (a cheap, high-signal check for the
  line-wrap rect bug specifically), (4) re-verify the TOC link count hasn't
  changed.
- When a person reports a bug from their own PDF viewer, ask for the actual
  file if results can't be reproduced — several "bugs" during development
  turned out to be stale test files or a different pipeline version, not
  real code issues. Don't debug blind against a screenshot alone if the
  actual PDF is available.

## No test PDF in this repo

There is deliberately no PDF committed here (licensing — this tool works on
copyrighted sourcebooks the end user must already own). That matters more
than it might seem: **every single bug documented above was found by running
against a real book and checking real output, not by reasoning about the
code in the abstract.** Several early attempts at this logic (an earlier
italic-based title matcher, an earlier "already linked" check) looked
correct on paper and were wrong the moment they hit actual text.

Consequences for anyone (human or Claude) working on this code without a
PDF in-repo:

- **Don't trust a change based on the code reading correctly.** Ask whoever
  you're working with to run it against their own legally-owned PDF locally
  and share the results (console output, the CSV report, and ideally a
  screenshot or a few extracted lines around anything that looks wrong) —
  never ask them to commit or upload the PDF itself.
- **Before touching the matching/rect-construction logic, ask for a
  small number of real repro lines from an actual failing case**, the same
  way bugs got found and fixed throughout this project's history: a page
  number, the visible text, and what actually happened vs. what should have
  happened. A hypothesis about *why* something might be broken is much less
  useful than one real example.
- **Treat a clean run (no exceptions, plausible-looking counts) as
  necessary, not sufficient.** The wrap-boundary rect bug, the false "already
  linked" skips, and the range-truncation bug all produced clean-looking
  runs with no errors — they just silently did the wrong thing. Ask for
  specific spot-checks, not just "did it run."
- If genuinely no one is available to test against a real file, the
  most useful thing to do is construct a **synthetic** test PDF containing
  fabricated placeholder text that deliberately exercises the known-tricky
  patterns from the bug list above (a reference wrapping across a line
  break, a narrow-space-glued trailing token, a hyphenated line-wrap mid-word,
  a "Chapters N-M" range, a fake native TOC link to confirm it's left alone,
  etc.) — none of that requires any real GURPS content, since the bugs are
  all structural, not content-specific. **This isn't just a theoretical
  suggestion**: building a minimal synthetic PDF from scratch (cover page +
  Contents page + numbered body pages, via `fitz.open()` /
  `doc.new_page()` / `page.insert_text()`) was what actually isolated bug
  #13 — it definitively separated "real bug in our logic" from "artifact
  of a flawed test setup" when a real book wasn't available to test the
  exact scenario needed.

## Known open limitations (not yet fixed, low priority)

- A reference back into the roman-numeral front matter (e.g. "see p. iv")
  is silently skipped — the range validator only understands arabic
  numbers. Rare enough (one known instance) that it hasn't been worth the
  added complexity of a dual numbering system.
- Cross-book detection's trigger word is now auto-detected from title
  metadata (see bug #18) rather than hardcoded, but the *title-shape*
  assumption after it (capitalized/title-cased words, common connectors
  allowed) is still fixed. A book that cites other titles in a
  differently-cased or differently-punctuated style may need
  `looks_like_title_span()` adjusted.
- Chapter extraction assumes the TOC's top-level entries are lines whose
  *first word* is a lone `"N."` token — this matches GURPS's convention but
  isn't a universal PDF/TOC standard.
- TOC-page detection in `hyperlink_pdf_universal.py` assumes the word
  "Contents" appears in the page's footer/header band, repeated on every
  page of that section (same pattern as Index detection). This is
  confirmed GURPS-specific, not universal — see bug #20, where real
  Mongoose books instead show the heading once, as a large one-off
  page-top title. `hyperlink_pdf_mongoose.py`'s `page_has_heading()`
  fixes this for that fork, but the limitation as described here still
  stands for `hyperlink_pdf_universal.py` itself — it hasn't been
  generalized back into the GURPS-line script, since every GURPS book
  tested so far does use the repeated-footer convention and there's been
  no real case forcing the change there.
- **Non-GURPS testing has now happened once** — see `hyperlink_pdf_mongoose.py`
  and bugs #20-#25 — against Mongoose Publishing's Traveller line (Core
  Rulebook, Companion, High Guard, Aliens of Charted Space). Several of
  the predictions in this bullet's previous version were confirmed
  correct (the `p.`/`pp.`-only grammar really did need extending — see
  bug #25's spelled-out "page"/"pages" support alongside the abbreviated
  form; the TOC/Index footer-word convention really did break, per bug
  #20 above) and some were more subtle than
  predicted (the title-metadata fallback wasn't just "irrelevant/inert,"
  it was actively wrong for one book — bug #23). **Still genuinely
  untested: any publisher other than these two.** Don't assume Mongoose's
  Traveller conventions generalize to a *third* publisher any more than
  GURPS's did to Mongoose — re-derive from real pages again, the same way
  both of these were derived.
