# MF Label Printer

Web app that makes Medium Format 50 x 30 mm barcode labels from DealPOS data or a Barcode Templater sheet, lets you change the label design, and prints through the iPhone 4Barcode app (PDF or Excel) or straight to the XP-TT426B over USB from the store tablet. Spec: `~/.claude/docs/specs/2026-11-11-mf-label-printer-design.md`.

It only reads DealPOS. Writes are refused in code (`read_only=True`, tested).

## Run it

Check without DealPOS or printer (fake data, throwaway designs):

```bash
uv run python scripts/dev_server.py        # http://127.0.0.1:8795  password: devpassword
uv run python scripts/ui_smoke.py          # drives the page in Chromium, mocked USB printer
uv run python scripts/ui_contrast.py       # WCAG contrast of the page in dark and light, exits 1 on a failure
uv run python scripts/ui_shots.py          # screenshots at 1280 / 768 / 390 px, both themes, into samples/ui/
```

The page is dark by default; the "Light theme" switch in the header changes it and the browser remembers the choice (`mf-theme` in localStorage).

Real (start from the Terminal panel, not as a background task of a Claude session):

```bash
vault run dealpos mf-label-printer -- uv run python -m labelprinter.server --port 8797
```

`vault` is found in PowerShell and the Terminal panel; Git Bash does not see it (use `vault.cmd` there).

Needs vault project `dealpos` (DealPOS keys, exists) and project `mf-label-printer` with `LABELPRINTER_PASSWORD` (12+ characters). Django sets that himself: `vault set mf-label-printer LABELPRINTER_PASSWORD`.

## Reach it from the store

Port 8797 is local only. The store tablet and phones use Tailscale Funnel on port 10000 (443 and 8443 belong to other apps; never touch them):

```bash
tailscale funnel --bg --https=10000 http://127.0.0.1:8797    # on: needs Django's OK, it is public behind the password
tailscale funnel --https=10000 off                           # off
```

URL: `https://YOUR-HOST.ts.net:10000`. The server is up only while this PC runs it. If it is down, use 4barcode-desktop and the Excel as before.

## Designs

A design is the label layout in millimetres: label size, gap, direction and a list of elements (text, barcode, line or box, logo). Built in and read-only: **MF Passport · symbol left** (the default the page opens with: brand DM Sans, the symbol and a flush-right barcode on one row, two machine-readable lines in DM Mono at the foot), **MF Price card** (ruled grid, barcode up the left edge), **MF Scan-safe** (the alternative: 2-dot barcode for scanners that miss 1-dot bars), **MF April** (your April layout, 6 pt text), **MF Large** (bigger type), **MF Stamp** (a Japanese postage stamp: perforated edge, record vignette, postmark with the year) and three other **MF Passport** placements of the symbol (under the price, in the header corner, at the end of the fields row), plus the brand and concept studies. Stamp and every Passport print any SKU length: their barcode runs the full width. In the default Passport the symbol gives way, and the barcode flips flush left, for the 11-13 character SKUs whose 2-dot bars need the whole width. Open "Edit the design" in the page, change elements by number, then Save or Save as. Your designs are files in `data/designs/`. Preview, PDF and USB print all use the design on screen, saved or not.

MF Brand designs (built in, from the brand guide): **Ledger**, **Barcode foot** and **Symbol column**. They are generated from one grid by `uv run python scripts/make_brand_designs.py` (2.5 mm margins, text on a 0.5 mm baseline grid, DM Sans 6 / 8 / 10 / 12 pt, SemiBold artist, Medium price and labels, Regular text, no black chips, the symbol at 6 mm or no mark). Edit that script, not the JSON files. `uv run python scripts/brand_preview.py --guides` renders sample labels with the margins and a 1 mm grid drawn on top. Text elements can sit on a baseline (`valign: baseline`, so a long line that shrinks stays on its line), be set in capitals (`upper`), and a design can draw its text smooth (`smooth_text`: drawn 4x and shrunk, for even letter spacing at small sizes). Logo files: `logo` (Sara's hand-drawn logotype, used by the older designs), `symbol`, `screen-logo` (at least 30 mm wide).

Barcode rule: bars print cleanly only when every bar is a whole number of printer dots. Mode `integer` guarantees that (1 dot = 0.125 mm, 2 dots = 0.25 mm). Mode `fit` stretches to the width you give, so bars alternate between 1 and 2 dots; the page warns about it. Run the scan test (below) before choosing.

## Printing

- **iPhone (main):** Download PDF, open it in the 4Barcode app (Files, Share, 4Barcode), print over Bluetooth. Page size is exactly 50 x 30 mm.
- **Excel (fallback):** Download Excel, use it with your existing 4Barcode design as before.
- **USB (tablet):** Chrome on the Android tablet, printer on a USB OTG cable, press Print over USB. The first press of a session prints 1 label; press again for the rest. Test labels: orientation label plus a scan-test label with the same barcode as A (1 dot), B (stretched), C (2 dots). Scan A, B, C with the POS scanner and keep the design whose barcode reads.
- **Test labels (PDF)** gives the same two test labels for the iPhone route.

## After the first real test print (set what you saw)

| You see | Fix |
|---|---|
| Black and white swapped | start the server with `LABELPRINTER_INVERT=1` |
| Image upside down or mirrored | design, Label, Direction 0 or 1, Save |
| Labels drift or skip | design, Label, Gap (mm), match the roll |
| The barcode will not scan | pick MF Scan-safe in the Design menu (2-dot bars, the alternative); to open the page on it, start the server with `LABELPRINTER_DEFAULT_DESIGN=mf-scan-safe` |
| A SKU of 14 or more characters | its bars are 1 dot (0.125 mm) wide on the Passport: read-test it on the printer, or print that record with MF Scan-safe; the Price card cannot print it at all |
| Text cut at the edge | move or narrow the element, the preview shows the exact print |

Record what worked here once known: _not tested on a unit yet_.

## Command line

```bash
vault run dealpos -- uv run python scripts/labels_cli.py AMEAMET158 ALEHEAC557 --copies 2 --design mf-scan-safe
vault run dealpos -- uv run python scripts/live_check.py AMEAMET158 ALEHEAC557     # read-only, shows what each label would say
uv run python scripts/make_samples.py "C:/Users/SER5 MAX/Documents/#MEDFOR/04APR/Barcode Templater April.xlsx" 9
```

## Notes

- Year and genre come from the DealPOS description (`Released: 2019`, `Genre: Rock`), which only newer products have. A year at the end of the title, like `Immunity (2019)`, moves to the year chip. Missing fields show amber and print blank; edit them in the table.
- DealPOS allows 50 requests per 180 s; the app paces itself (45). Year and genre lookups are one request per product and cached for a day.
- Fonts: a text element can use any font installed on this PC (`C:/Windows/Fonts`; set `LABEL_FONT_DIR` to use another folder), DM Sans (the MF brand font, bundled in `labelprinter/fonts`), or a `.ttf` / `.otf` file you add with "Add a font file" in the design editor (kept in `data/fonts`, 5 MB each; added fonts get a Remove button). Light, Black and other weights are listed as their own fonts ("Lato Light"). A design that names a font this PC does not have still prints, in Arial, and the page says so. `py scripts/make_dmsans.py` regenerates the DM Sans files (needs fontTools, only for that script).
- Static files (page code and fonts) are public; every data and download route needs the login cookie.
- Tests: `uv run pytest -q`.
