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
built for GURPS sourcebooks, but the detection is mostly generic). Given a
PDF with plain text like "see p. 208" or "Chapters 11-13", it finds every
such reference, works out which physical page it means, and inserts a
clickable link — without needing any external lookup table, without touching
already-correct links (e.g. a publisher's native Table of Contents), and
without linking a reference that's actually citing a *different* book.

## Files

| File | Purpose |
|---|---|
| `hyperlink_pdf_universal.py` | **Current active development version — start here.** Superset of everything below: page references, Index, chapter references (including comma-separated lists like "Chapters 2, 4, and 6"), GURPS book-code shorthand (`p. B123`), an auto-detected cross-book trigger word (pulled from the PDF's own title metadata instead of hardcoded "GURPS"), a known-title allowlist for bare italicized citations ("High-Tech, pp. 13-15" with no "GURPS" prefix), and a TOC self-hyperlinking pass for books that ship without one (see below). Validated against multiple real GURPS books, including a non-Basic-Set supplement (GURPS High-Tech: Electricity and Electronics) and GURPS Space specifically for the TOC feature. **Next planned step (not yet done): testing against non-GURPS PDFs** — see "GURPS-specific vs. generic" below for what's known to be hardcoded. |
| `hyperlink_pdf.py` | The original stable, verified version predating the universal rewrite. Links `p. NNN` / `pp. NNN-NNN` page references and Index-style bare numbers only — no chapters, no TOC self-linking, no book-code/italic-title cross-book detection. Kept as a known-good fallback reference point. |
| `hyperlink_pdf_v2_chapters.py` | Intermediate version, superseded by `hyperlink_pdf_universal.py`. Kept for history; no reason to use it over the universal version now. |
| `crop_to_center.py` | Unrelated preprocessing tool: crops mismatched left/right margins so text is centered. Not required for hyperlinking; only relevant if starting from a raw, uncropped scan/export. |
| `extract_links.py` / `apply_links.py` | A manifest-based pair for migrating a verified set of links from one copy of a book onto a *different* copy (e.g. a differently-cropped or differently-compressed export of the same content). Not part of the normal hyperlinking workflow — only useful if you have a known-good hyperlinked file and need to transplant its links elsewhere. |
| `remove_cross_book_links.py` | Standalone cleanup pass: scans an *already-linked* PDF and removes any link that was wrongly created for a different-book reference. Useful if the cross-book filter is later found to have missed a case. |
| `unlinked_report.py` | Audits a PDF and reports every reference-shaped piece of text that has no link, classified by likely reason (out of range / other-book title nearby / unexplained). The "unexplained" bucket is the useful one — anything there is probably a real gap. |
| `combine_books.py` | Merges the GURPS Basic Set, 4E Characters and Campaigns PDFs into one file (deletes a few cut-content pages, splices the two front matters/TOCs together, moves both books' `II` pages to the end, relabels the merged front matter as sequential lowercase roman numerals, sets metadata + an open-to-Contents action), then optionally (`--hyperlink`, off by default) hyperlinks the result. Hardcodes the specific page labels to move/delete for this exact pair of books — not a general merger. Every page label is reconstructed from scratch and independently verified against the source labels before the merge step reports success. The merge step uses `pypdf`'s writer/append pattern (see bugs #6/#7 below) rather than `pikepdf` — that's normally avoided in this pipeline, but reordering/deleting pages here genuinely requires rebuilding the page tree, and the script explicitly reconstructs `/PageLabels` and `/Info` metadata afterward rather than assuming pypdf preserves them. The `--hyperlink` step is a **separate, later pass**, opening the just-written file fresh with PyMuPDF (`fitz`) — it does not touch or extend the pypdf writer object. Its reference-matching logic (regexes, cross-book detection, rect-safety checks) is a full inline copy of `hyperlink_pdf_universal.py`'s, kept independent on purpose since this is a one-off pipeline for exactly one merged file; but its page-number resolution is deliberately *not* copied from that script — see bug #19 below for why. |

## Core architecture

- **Nothing about page numbering is hardcoded.** The printed-page-label
  scheme (roman front matter, arabic body, whatever offset applies) is
  detected by scanning every page's footer/header band for digit tokens and
  taking the *mode* of `(pdf_index - printed_number)` across the whole
  document. This is robust to a handful of noisy/wrong footer reads but will
  need re-thinking for a book with a fundamentally different numbering
  scheme (e.g. per-chapter restarts) — confirmed in practice by bug #19
  below, where a file spliced together from two independently-paginated
  books broke this assumption outright; `combine_books.py` works around
  it locally rather than fixing it here, so this limitation still stands
  for this function/script.
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
    glued together** — confirmed on `combine_books.py`'s merged
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
    bug; it's binary per book. **Fix, scoped to `combine_books.py` only**
    (deliberately *not* applied to `hyperlink_pdf_universal.py` itself —
    see the "Nothing about page numbering is hardcoded" bullet under
    "Core architecture" above, which this confirms in practice):
    `combine_books.py` already builds and verifies `combined_labels`, the
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
- TOC-page detection assumes the word "Contents" appears in the page's
  footer/header band (same pattern as Index detection). A book that labels
  it differently, or puts the label somewhere other than the footer band,
  won't be recognized as having a TOC at all — meaning both chapter
  extraction *and* the TOC self-hyperlinking feature would silently find
  nothing to do, without erroring.
- **Not yet tested against a non-GURPS book, as of this writing.** Known
  GURPS-specific assumptions that will need real testing (not guessing) to
  know what actually breaks: the `p.`/`pp.` abbreviation-only reference
  grammar (a publisher who writes "page" in full won't match at all), the
  `KNOWN_GURPS_TITLES` allowlist (irrelevant, harmlessly inert, for a
  different publisher), the book-code shorthand check (same — harmlessly
  inert elsewhere), and the "N." chapter/TOC conventions above. None of
  these should *break* on a non-GURPS book — worst case they just find
  zero matches for that particular feature — but that also means zero
  cross-book protection for whatever citation style a different publisher
  actually uses, which is the thing most worth verifying first.
