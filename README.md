# GURPS PDF Reference Hyperlinker

Automatically turns in-text page and chapter references in a PDF sourcebook
("see p. 208," "Chapters 11-13," an index entry like "Accents, 24.") into
clickable hyperlinks that jump straight to the right page — no manual
clicking through the table of contents, no external app.

Built and tested against GURPS Basic Set, Fourth Edition Revised (and, for
some features, GURPS High-Tech: Electricity and Electronics and GURPS
Space). **This tool is GURPS-specific** — the reference grammar it looks
for (`p.`/`pp.` abbreviations, `Chapter N` wording, GURPS's book-code
shorthand, a hardcoded list of GURPS product titles) matches GURPS's own
conventions, and it has not been tested against a PDF from any other RPG
publisher. It may partially work on a non-GURPS book (or it may silently
find nothing), but that hasn't been verified — see **Limitations** below.

## What it does

The current, actively developed script is `hyperlink_pdf_universal.py` —
that's the one to use unless you have a specific reason to reach for one of
the older scripts described further down. It:

- Finds `p. NNN` / `pp. NNN-NNN` style page references in body text and
  links them to the actual page.
- Finds Index-style bare number references (`Term, 24.`, `Term, 418-425.`)
  and links those too, including ranges that word-wrap across a line break.
- Finds explicit chapter references ("see Chapter 6," "Chapters 11-13,"
  "Chapters 2, 4, and 6") and links them to that chapter's opening page.
- Recognizes GURPS's own book-code shorthand (`p. B123`, `p. MA45`) as a
  reference to a *different* book, and skips linking it into this one.
- Recognizes a handful of known GURPS product titles cited bare, without
  the word "GURPS" in front (e.g. "High-Tech, pp. 13-15" inside a
  High-Tech supplement), and skips those too.
- **Leaves a book's existing Table of Contents alone**, and can add links
  to one that doesn't have any — if a TOC's dot-leader entries are mostly
  unlinked, it hyperlinks each one's trailing page number itself.
- **Tries not to link references to a *different* book.** A citation like
  "GURPS Powers, p. 40" won't get linked into *this* book's own page 40,
  even though "40" is a valid page number here too. The trigger word for
  this ("GURPS") is auto-detected from the PDF's own title metadata, not
  hardcoded, so it's not strictly limited to GURPS books.
- Writes a CSV report alongside each output PDF listing every reference
  found, whether it got linked, and why not if it didn't — so you can
  spot-check the results instead of trusting a bare "N links added" count.
- Can process a single PDF, or an entire folder of them at once (see
  **Batch-processing a folder** below).

## Installation

**Easiest option: double-click setup.** This repo includes a setup script
that does everything below for you automatically.

- **macOS**: double-click `setup.command`.
- **Windows**: double-click `setup.bat`.

First time running it, your OS will probably show a security warning since
it's not a signed/notarized app (this is normal for scripts downloaded from
GitHub, not a sign anything's wrong):
- **macOS**: right-click `setup.command` → **Open** → then click **Open**
  again in the dialog that pops up. (Only needed the first time —
  double-clicking normally works after that.)
- **Windows**: if SmartScreen blocks it, click **More info** → **Run
  anyway**.

The script installs Python (and Homebrew, on macOS, if you don't have it)
and the required packages, then tells you the command to run the tool
itself. If it fails partway through, the manual steps below explain what
it's doing and why, which makes it easier to spot where things went wrong.

<details>
<summary><strong>Manual setup instead (click to expand)</strong></summary>

### macOS

These steps assume a completely fresh Mac with no developer tools
installed. If you already have Homebrew and Python set up, skip to step 3.

**1. Install Homebrew** (a package manager — it's what lets you install
Python with one command instead of hunting down installers)

Open the **Terminal** app (search for it with Spotlight — `Cmd+Space`, type
"Terminal") and paste in:

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Press Enter, then follow whatever instructions it prints (it may ask for
your Mac password, and may tell you to run one or two more commands
afterward to finish adding Homebrew to your PATH — if so, copy-paste those
exactly as shown).

**2. Install Python**

```
brew install python3
```

Confirm it worked and that you're actually using the new one, not the old
version Apple ships by default:

```
python3 --version
```

This should print `Python 3.11` or higher. If it prints `Python 3.9.6`,
Homebrew's Python isn't first on your PATH yet — close and reopen Terminal
and try again before moving on.

**3. Download this repository**

Click the green **Code** button on this GitHub page → **Download ZIP** →
unzip it. Or, if you're comfortable with git:

```
git clone https://github.com/plazman30/gurps_4e_revised_hyperlink.git
```

**4. Open Terminal in that folder**

Find the unzipped/cloned folder in Finder, then either drag the folder icon
onto the Terminal app's icon, or type `cd ` (with a trailing space) into
Terminal and drag the folder into the window — either way it fills in the
path for you. Press Enter.

**5. Install the required packages**

```
python3 -m pip install -r requirements.txt --break-system-packages
```

That `--break-system-packages` flag looks alarming, but it's not — it just
tells Homebrew's Python "yes, I really do want to install this here," and
won't affect anything else on your Mac.

You're set up. Move on to **Usage** below (macOS commands use `python3`).

### Windows

**1. Install Python**

Go to **[python.org/downloads](https://www.python.org/downloads/)** and
click the big yellow **Download Python** button. Run the installer once
it's downloaded.

⚠️ **On the very first installer screen, check the box at the bottom that
says "Add python.exe to PATH" before clicking Install Now.** This is the
single most common thing people miss, and if you skip it, Windows won't be
able to find the `python` command afterward — you'd have to uninstall and
run the installer again with the box checked.

**2. Confirm it worked**

Open **Command Prompt** (click Start, type `cmd`, press Enter) and type:

```
python --version
```

This should print `Python 3.11` or higher. If you instead see something
like *"'python' is not recognized as an internal or external command"*,
the PATH checkbox from step 1 got missed — reinstall and make sure to check
it.

**3. Download this repository**

Click the green **Code** button on this GitHub page → **Download ZIP**,
then right-click the downloaded file → **Extract All** to unzip it.

**4. Open Command Prompt in that folder**

Open the extracted folder in File Explorer, click in the address bar at the
top, type `cmd`, and press Enter — this opens a Command Prompt already
pointed at that folder. (On Windows 11 you can also right-click inside the
folder and choose **Open in Terminal**.)

**5. Install the required packages**

```
python -m pip install -r requirements.txt
```

Windows doesn't have the same restriction macOS's Homebrew Python does, so
no extra flags are needed here — if this command just runs without
complaint, you're done.

You're set up. Move on to **Usage** below — but on Windows, use `python`
instead of `python3` in the commands (Windows' installer doesn't create a
`python3` alias the way macOS/Linux do).

</details>

## Usage

### Single file

```
python3 hyperlink_pdf_universal.py YourBook.pdf YourBook_linked.pdf
```

*(Windows: use `python` instead of `python3`.)*

*(If you downloaded a ZIP instead of using git, make sure `YourBook.pdf` is
either in that same folder, or type the full path to wherever it's saved.)*

That's it — page numbering, the Index section, chapter list, and
everything else needed is auto-detected from the file itself; nothing
needs to be configured for a specific book. It writes
`YourBook_linked_link_report.csv` alongside the output with a full log of
what happened.

### Batch-processing a folder

To process every PDF in a folder in one go, use `--batch` with the folder
path instead of an input/output file pair:

```
python3 hyperlink_pdf_universal.py --batch YourBooks/
```

This creates a new folder called `YourBooks-hyperlinked/` *next to*
`YourBooks/` (not inside it), and writes one linked PDF plus one CSV report
into it for every PDF found directly inside `YourBooks/`.

Two optional flags:

- **`--recursive`** (alias `--recursives`) — also look inside subfolders of
  `YourBooks/`, not just the top level. The same subfolder layout is
  recreated inside `YourBooks-hyperlinked/`.
- **`--rename`** — append `-hyperlinked` to each output filename (e.g.
  `Basic Set.pdf` → `Basic Set-hyperlinked.pdf`) instead of keeping the
  original name. Useful if you'll be moving files back out of the
  per-folder structure later and want the filename itself to say what
  happened to it.

```
python3 hyperlink_pdf_universal.py --batch --recursive --rename YourBooks/
```

A PDF that fails partway through (e.g. one with no readable page numbers
in its footers) doesn't stop the rest of the batch — it's reported and
skipped, and everything else still gets processed.

### Other scripts in here

| Script | What it's for |
|---|---|
| `hyperlink_pdf.py` | The original, more limited version — page and Index references only, no chapters, no batch mode. Kept as a known-good fallback if `hyperlink_pdf_universal.py` ever regresses on a book it used to handle. |
| `hyperlink_pdf_v2_chapters.py` | An intermediate version between the two above. Superseded by `hyperlink_pdf_universal.py` — no reason to reach for this one now. |
| `setup.command` / `setup.bat` | One-click installer (macOS / Windows) — see **Installation** above. |
| `crop_to_center.py` | Optional preprocessing: crops uneven left/right margins so text is centered on the page. Not needed for hyperlinking — only useful if you're starting from a raw scan/export with inconsistent margins. Preserves page labels, existing links, and metadata (a plain `pypdf`-based crop won't). |
| `unlinked_report.py` | Audits an *already-linked* PDF and reports every reference-looking piece of text that still has no link, with a best guess at why (out of range / looks like a different book / genuinely unexplained). Good for double-checking a run before calling it done. |
| `remove_cross_book_links.py` | Cleanup pass for an existing file: finds and removes any link that was wrongly created for a different-book reference. |
| `combine_books.py` | Merges the GURPS Basic Set, 4th Edition PDFs (Characters + Campaigns) into one combined book: drops a handful of cut-content pages, splices each book's front matter and table of contents together, moves both copyright/title (`II`) pages to the very end, relabels the merged front matter with sequential lowercase roman numerals, and sets the file's title/author/subject metadata plus an open-to-Contents action — all while keeping every other page's original page label intact. Book-specific (hardcodes which page labels move/delete for this exact pair of books), not a general-purpose PDF merger. Add `--hyperlink` to also link every in-text page/chapter reference in the merged file afterward (off by default — without it, the output is just the combined PDF with no links). This isn't just `hyperlink_pdf_universal.py` called on the result: that script's page-numbering detection assumes one constant offset for the whole book, which doesn't hold once two separately-paginated books are spliced together, so it has its own self-contained copy of the linking logic that looks up each page number directly instead. See `python3 combine_books.py --help` for full usage. |
| `extract_links.py` / `apply_links.py` | Advanced use only — lets you pull a verified set of links out of one copy of a book and reapply them onto a *different* copy (e.g. a differently cropped or compressed export of the same content), matching by text rather than raw coordinates. Not part of the normal workflow. |

## Limitations (read before trusting the output blindly)

- **Not tested on any non-GURPS publisher's PDF.** Everything above has
  only been verified against actual GURPS books. The `p.`/`pp.` and
  `Chapter N` reference styles, the GURPS book-code shorthand, and the
  hardcoded GURPS product-title list are all GURPS conventions — a
  different publisher's book may use different wording entirely (e.g.
  spelling out "page" or "chapter six" instead), in which case this tool
  would likely find few or no references to link, without erroring.
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

If you find a reference that isn't getting linked (or one that's getting
linked incorrectly), the most useful bug report is: the page number, the
exact visible text, and what actually happened vs. what should have
happened. That's how every fix in this project's history actually got
made — against real examples, not guesses. See `CLAUDE.md` if you're
working on this with Claude Code; it documents a long list of
non-obvious bugs already found and fixed, worth reading before touching
the matching logic.
