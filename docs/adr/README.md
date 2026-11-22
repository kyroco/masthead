# Decision records

Masthead's architecture decision records (ADRs) live in this folder, one file
each, named `ADR-NNNN-short-title.md`. `.claude/settings.json` names it as
`ADR_DIR`, so the ADR gates check new records here against the shape in
`hooks/adr_shape.py`. `references/gate-catalog.md` lists what they do not see,
such as a record written through the shell by a relative path.

They used to live in the GitHub wiki. A cloud session cannot reach a wiki, so
records live in the repository now (MAST-53). Robert moves the old wiki pages
here himself.
