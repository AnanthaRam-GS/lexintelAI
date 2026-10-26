# Self-hosted fonts (step 20)

The two UI typefaces are committed here so that `next build` needs no network access to Google Fonts. `app/fonts.ts`
loads them with `next/font/local`. It reproduces the `@font-face` rules that `next/font/google` generated before:
the same files, families, weights, `unicode-range` subsets, `font-stretch`, `display: swap` and preloads (latin only).
`fonts.css` holds the `--font-display` and `--font-ui` variables and the metric-matched fallback faces, with the values
`next/font/google` generated.

| File                                            | Family                                           | Subset       | Licence                     |
| ----------------------------------------------- | ------------------------------------------------ | ------------ | --------------------------- |
| `libre-baskerville-latin-wght-normal.woff2`     | Libre Baskerville 2.005 (variable, wght 400–700) | latin        | `OFL-Libre-Baskerville.txt` |
| `libre-baskerville-latin-ext-wght-normal.woff2` | Libre Baskerville 2.005 (variable, wght 400–700) | latin-ext    | `OFL-Libre-Baskerville.txt` |
| `ibm-plex-sans-latin-wght-normal.woff2`         | IBM Plex Sans 3.201 (variable, wght 100–700)     | latin        | `OFL-IBM-Plex-Sans.txt`     |
| `ibm-plex-sans-latin-ext-wght-normal.woff2`     | IBM Plex Sans 3.201                              | latin-ext    | `OFL-IBM-Plex-Sans.txt`     |
| `ibm-plex-sans-vietnamese-wght-normal.woff2`    | IBM Plex Sans 3.201                              | vietnamese   | `OFL-IBM-Plex-Sans.txt`     |
| `ibm-plex-sans-greek-wght-normal.woff2`         | IBM Plex Sans 3.201                              | greek        | `OFL-IBM-Plex-Sans.txt`     |
| `ibm-plex-sans-cyrillic-wght-normal.woff2`      | IBM Plex Sans 3.201                              | cyrillic     | `OFL-IBM-Plex-Sans.txt`     |
| `ibm-plex-sans-cyrillic-ext-wght-normal.woff2`  | IBM Plex Sans 3.201                              | cyrillic-ext | `OFL-IBM-Plex-Sans.txt`     |

**Source.** These are the exact files Google Fonts (`fonts.gstatic.com`) served to `next/font/google` (Next.js
16.3.8, from `main`'s lockfile) when `main` was built in GitHub Actions on 2026-10-26: run 40282345632 of the temporary `font-compare`
workflow. They are byte-identical to that build's `.next/static/media` files and are copied unchanged, only renamed.

The first attempt used Fontsource's static instances (`@fontsource/*@5.3.0`). They are the same font versions, but
their advance widths round differently from Google's variable files, and screenshots differed by up to 2% of pixels.

**Licence.** Both families are under the SIL Open Font License 1.1 (copyright 2012 The Libre Baskerville Project
Authors; copyright 2019 IBM Corp.). The licence texts are the `LICENSE` files of the
`@fontsource/*@5.3.0` packages (the upstream OFL texts with each family's copyright line). The OFL allows the fonts to be
bundled and redistributed with software, provided the licence travels with them and the fonts are not sold on their
own.
