# PDF Reference Hyperlinker

Automatically turns in-text page and chapter references in a PDF sourcebook
("see p. 208," "Chapters 11-13," an index entry like "Accents, 24.") into
clickable hyperlinks that jump straight to the right page — no manual
clicking through the table of contents, no external app.

Built and tested against GURPS Basic Set, Fourth Edition Revised, but the
detection logic isn't hardcoded to that book specifically.

## What it does

- Finds `p. NNN` / `pp. NNN-NNN` style page references in body text and
  links them to the actual page.
- Finds Index-style bare number references (`Term, 24.`, `Term, 418-425.`)
  and links those too, including ranges that word-wrap across a line break.
- Optionally (see `hyperlink_pdf_v2_chapters.py`) finds explicit chapter
  references ("see Chapter 6," "Chapters 11-13") and links them to that
  chapter's opening page.
- **Leaves a book's existing Table of Contents alone.** If a spot already
  has a working link, nothing new gets added there — this is how the native
  TOC survives untouched without the script needing to know anything about
  where the TOC is.
- **Tries not to link references to a *different* book.** A citation like
  "GURPS Powers, p. 40" won't get linked into *this* book's own page 40,
  even though "40" is a valid page number here too.
- Writes a CSV report alongside the output PDF listing every reference
  found, whether it got linked, and why not if it didn't — so you can
  spot-check the results instead of trusting a bare "N links added" count.

## Requirements

```
pip install -r requirements.txt
```

That's the only dependency ([PyMuPDF](https://pymupdf.readthedocs.io/)).
Python 3.8+.

## Usage

```
python3 hyperlink_pdf.py YourBook.pdf YourBook_linked.pdf
```

That's it — page numbering, the Index section, and everything else needed
is auto-detected from the file itself; nothing needs to be configured for
a specific book. It writes `YourBook_linked_link_report.csv` alongside the
output with a full log of what happened.

**Chapter references too?** Use `hyperlink_pdf_v2_chapters.py` the same
way. It does everything above plus chapter-number linking. Kept as a
separate script rather than merged into the main one because it's newer
and less extensively tested — try it, but check the report a bit more
carefully.

### Other scripts in here

| Script | What it's for |
|---|---|
| `crop_to_center.py` | Optional preprocessing: crops uneven left/right margins so text is centered on the page. Not needed for hyperlinking — only useful if you're starting from a raw scan/export with inconsistent margins. Preserves page labels, existing links, and metadata (a plain `pypdf`-based crop won't). |

## Limitations (read before trusting the output blindly)

- **It can't perfectly tell "this page number is in my own book" from "this
  page number happens to match, but the sentence is citing a different
  book."** The cross-book filter catches the common phrasing ("GURPS
  `<Title>`, p. NNN") but isn't foolproof. Skim the CSV report, especially
  anything near a mention of another book's name.
- Only handles the `p.`/`pp.` abbreviation style for page references, and
  the `Chapter N` / `Chapters N-M` style for chapter references. A book
  that spells out "page 208" or "in the sixth chapter" instead won't be
  caught without adjusting the regex patterns near the top of the script.
- The Index detection looks for the word "Index" in a page's
  footer/header. A book that labels it something else (e.g. "Glossary")
  needs `INDEX_HEADER_WORDS` adjusted.
- If your PDF is a scan without a real text layer (no selectable text),
  none of this will find anything — it needs embedded, extractable text.
- A reference pointing back into roman-numeral front matter (e.g. "see
  p. iv") isn't currently linked — the page-number logic only understands
  arabic numbers.

## A note on what's *not* here

There's no PDF in this repo, and there won't be — this tool operates on
copyrighted sourcebooks that you need to already own a copy of. Point it at
your own legally purchased PDF.

## Contributing / reporting issues

**PLEASE TEST AND REPORT MISSING OR INCORRECT LINKS!!!**

If you find a reference that isn't getting linked (or one that's getting
linked incorrectly), the most useful bug report is: the page number, the
exact visible text, and what actually happened vs. what should have
happened. That's how every fix in this project's history actually got
made — against real examples, not guesses. See `CLAUDE.md` if you're
working on this with Claude Code; it documents a long list of
non-obvious bugs already found and fixed, worth reading before touching
the matching logic.

# PLEASE NOTE

This script is for your **LEGALLY PURCHASED** copy of GURPS 4E Revised. If you find a missing or incorrect link in your **LEGALLY PURCHASED** copy please report it and I will fix it. If you got your PDF  from some sketchy website, torrent or other source, there is no way to know what processing was done to the PDF by other unscrupulous individuals. By fixing your issue, I could potentially break the script for the rest of us. I'm not judging you. Just pointing out that I really can't fix an issue I can't duplicate.

**THAT BEING SAID**, I got my PDF from the Ring of Fire Backerkit campaign. I have to assume that the version I have is the same as the one on Warehouse23.com. But since they haven't added the PDF to my Warehouse23 account yet, I can't be completely sure of that.
