# AGENTS.md

This file exists for coding agents/tools that specifically look for
`AGENTS.md` rather than `CLAUDE.md`. There is no separate content here —
**read `CLAUDE.md` in full before touching anything in this repo.** It is
the single source of truth for this project's context, architecture, and
(most importantly) the bug history.

The short version, if you read nothing else: this tool was built by
finding real bugs against a real book, one at a time, over many rounds.
Several of them are the kind that produce a clean run and a
plausible-looking result while silently doing the wrong thing. `CLAUDE.md`
documents 38 of these in detail — what broke, how it was found, and how it
was fixed — specifically so they don't get reintroduced by a rewrite that
looks correct on paper. Skimming the summary and skipping the bug list is
the fastest way to redo work that's already been done once. (Some of the
other, non-hyperlinking utilities documented in `CLAUDE.md`'s Files table —
`convert_pdf_to_grayscale.py`, `castles_and_crusades_background_layer.py`,
and others — have their own bug/lesson history written inline in their own
table entries rather than in the numbered list, which is specific to the
hyperlink-matching logic.)

There is no PDF committed in this repo (licensing), so `CLAUDE.md` also
explains what "verified" means here and how to test changes without one.
