# Self-hosted fonts (step 20)

The two UI typefaces are committed here so that `next build` needs no network access to Google Fonts. They replace
`next/font/google` with `next/font/local` in `app/layout.tsx`; family, weights, subset (latin), `display: swap` and
the CSS variables are unchanged.

| File | Family | Weight | Licence |
|---|---|---|---|
| `libre-baskerville-latin-400-normal.woff2` | Libre Baskerville | 400 | `OFL-Libre-Baskerville.txt` |
| `libre-baskerville-latin-700-normal.woff2` | Libre Baskerville | 700 | `OFL-Libre-Baskerville.txt` |
| `ibm-plex-sans-latin-400-normal.woff2` | IBM Plex Sans | 400 | `OFL-IBM-Plex-Sans.txt` |
| `ibm-plex-sans-latin-500-normal.woff2` | IBM Plex Sans | 500 | `OFL-IBM-Plex-Sans.txt` |
| `ibm-plex-sans-latin-600-normal.woff2` | IBM Plex Sans | 600 | `OFL-IBM-Plex-Sans.txt` |
| `ibm-plex-sans-latin-700-normal.woff2` | IBM Plex Sans | 700 | `OFL-IBM-Plex-Sans.txt` |

**Source.** The `files/` directories of the npm packages `@fontsource/libre-baskerville@5.3.0` and
`@fontsource/ibm-plex-sans@5.3.0` (Fontsource repackages the Google Fonts files), downloaded 2026-10-26 with
`npm pack`. The files are copied unchanged.

**Licence.** Both families are under the SIL Open Font License 1.1 (copyright 2012 The Libre Baskerville Project
Authors; copyright 2019 IBM Corp.). The licence texts are the packages' own `LICENSE` files. The OFL allows the fonts
to be bundled and redistributed with software, provided the licence travels with them and the fonts are not sold on
their own.
