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
| `hyperlink_pdf.py` | **The stable, verified version.** Links `p. NNN` / `pp. NNN-NNN` page references (body text) and Index-style bare numbers (`Term, 24.`). Standalone — run directly on any copy of the PDF. |
| `hyperlink_pdf_v2_chapters.py` | Everything `hyperlink_pdf.py` does, plus links explicit `Chapter N` / `Chapters N-M` references to that chapter's opening page. Newer, less battle-tested than the base version — keep as a separate file rather than merging until it's proven equally solid. |
| `crop_to_center.py` | Unrelated preprocessing tool: crops mismatched left/right margins so text is centered. Not required for hyperlinking; only relevant if starting from a raw, uncropped scan/export. |
| `extract_links.py` / `apply_links.py` | A manifest-based pair for migrating a verified set of links from one copy of a book onto a *different* copy (e.g. a differently-cropped or differently-compressed export of the same content). Not part of the normal hyperlinking workflow — only useful if you have a known-good hyperlinked file and need to transplant its links elsewhere. |
| `remove_cross_book_links.py` | Standalone cleanup pass: scans an *already-linked* PDF and removes any link that was wrongly created for a different-book reference. Useful if `hyperlink_pdf.py`'s cross-book filter is later found to have missed a case. |
| `unlinked_report.py` | Audits a PDF and reports every reference-shaped piece of text that has no link, classified by likely reason (out of range / other-book title nearby / unexplained). The "unexplained" bucket is the useful one — anything there is probably a real gap. |

## Core architecture

- **Nothing about page numbering is hardcoded.** The printed-page-label
  scheme (roman front matter, arabic body, whatever offset applies) is
  detected by scanning every page's footer/header band for digit tokens and
  taking the *mode* of `(pdf_index - printed_number)` across the whole
  document. This is robust to a handful of noisy/wrong footer reads but will
  need re-thinking for a book with a fundamentally different numbering
  scheme (e.g. per-chapter restarts).
- **The Table of Contents is never explicitly detected or special-cased.**
  It's protected implicitly: before inserting any link, the code checks
  whether that spot is already linked, and a publisher's native TOC already
  has its own correct links. This is simpler and more robust than trying to
  identify "TOC pages" by structure.
- **The Index** *is* explicitly detected, via a footer/header word match
  (default: "index"), because it needs a different reference grammar (bare
  `Term, 24.` numbers, not `p. NNN`) and applying that grammar to ordinary
  body text would cause massive false-linking of unrelated numbers.
- **Cross-book reference detection** looks for a trigger word (default
  `"gurps"`) followed by a run of words that looks like a product title
  (capitalized or digit-starting, common connectors like "and"/"of" allowed,
  no embedded sentence-ending punctuation) sitting immediately before a
  reference. This is what stops "GURPS Powers, p. 40" from linking into
  *this* book's own page 40.

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
  all structural, not content-specific.



- A reference back into the roman-numeral front matter (e.g. "see p. iv")
  is silently skipped — the range validator only understands arabic
  numbers. Rare enough (one known instance) that it hasn't been worth the
  added complexity of a dual numbering system.
- Cross-book detection depends on the trigger word `TITLE_TRIGGER_WORD`
  (default `"gurps"`) and assumes titles are capitalized/title-cased
  immediately after it. A book that abbreviates its own line's name
  differently will need this adjusted.
- Chapter extraction assumes the TOC's top-level entries are lines whose
  *first word* is a lone `"N."` token — this matches GURPS's convention but
  isn't a universal PDF/TOC standard.
