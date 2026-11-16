# open-multiples

Public-company valuation comps built only from free, reusable sources. Every number links back to the SEC filing it came from.

This first slice computes LTM and FY financials, growth, margins, expense ratios and the EV bridge from SEC EDGAR XBRL, for every US filer and IFRS 20-F/40-F filer. Market cap, EV and every multiple are computed once you supply a licensed price.

The details are in [METHODOLOGY.md](METHODOLOGY.md). The project is pure Python 3.10+ with no pip dependencies.

## Setup

```bash
cd ~/Downloads/open-multiples
```

```bash
cp .env.example .env
```

Set `SEC_USER_AGENT` in `.env` to your name or organisation plus a contact email. SEC's fair-access policy requires it for the ticker list and bulk files.

## Use

```bash
python3 open_multiples.py show AAPL
```

```bash
python3 open_multiples.py build AAPL MSFT NVDA JPM --prices my_prices.csv
```

```bash
python3 open_multiples.py build --all
```

```bash
python3 open_multiples.py build --all --as-of 2025-06-30
```

- `show` prints one company, with every field linked to its source filing.
- `build` writes `data/out/public_comps.csv`, plus a `.jsonl` copy and `provenance.jsonl`.
- `build --all` covers every listed SEC filer, about 6–7k companies, at ≤8 requests/second.
- `--as-of` gives a point-in-time view that uses only filings made by that date.

`--cik 320193` works in place of tickers, and doesn't need the SEC ticker list. To fetch everything in one file instead of per-company calls, run `python3 open_multiples.py bulk-download`, which downloads SEC's nightly `companyfacts.zip` (over 1 GB).

## M&A precedent multiples (from merger filings)

```bash
python3 open_multiples.py ma --from 2026-01-01 --to 2026-11-15
```

```bash
python3 open_multiples.py ma --url https://www.sec.gov/Archives/edgar/data/1527753/000119312526427872/d141436ddefm14a.htm
```

The first command searches a date range. The second parses a single filing.

`ma` searches EDGAR full text for merger proxies, S-4s and 14D-9s that contain a "Selected Precedent Transactions Analysis". It then reads each banker's table and writes three files:

- `data/out/ma_precedent_observations.csv`: one row per filing × banker × deal × multiple. Each row carries the accession number, URL, advisor and raw cell text.
- `data/out/ma_analyses.csv`: one row per banker analysis, with its summary rows (median/mean) and the reference range the banker selected.
- `data/out/ma_deals.csv`: deals merged across filings, by target + acquirer + announce month (±2 months). It holds the median per multiple type, the number of sources, and a flag where sources disagree by more than 10%.

`kind` separates multiples (ratios) from amounts (deal value or target revenue in $M, as printed). Multiples that are ≤ 0 or above 250× are marked `nm`.

**Known gaps:**
- Tables that list deals without per-deal multiples are kept as identity-only rows. Some banks give only the summary statistics in the text.
- Bank-merger tables (price/tangible book, core deposit premium) that use non-standard headers aren't fully matched yet.
- The subject deal's own headline price isn't extracted yet.

## Document search (AlphaSense-style)

Index the full text of filings, search them with keyword operators, and track mentions over time.

```bash
python3 open_multiples.py ingest AAPL MSFT NVDA --since 2025-01-01
```

```bash
python3 open_multiples.py search '"pricing pressure"' --form 10-K 10-Q --section "Risk Factors" --trend
```

```bash
python3 open_multiples.py search 'tariff* NOT china' --save tariffs
```

```bash
python3 open_multiples.py alerts
```

```bash
python3 open_multiples.py serve
```

- **`ingest`** indexes 10-K, 10-Q, 8-K (plus EX-99 earnings releases), 20-F, 6-K, proxies, S-1 and S-4 filings. Add `--all` for every listed filer.
- **`search`** supports filters, a mentions-per-quarter trend (`--trend`), and saving as an alert (`--save`).
- **`alerts`** shows new filings that match each saved search since the last run. Schedule it with cron.
- **`serve`** opens a web UI at http://127.0.0.1:8765 with filters, clickable facets, a mentions chart, a passage viewer and saved searches.

Query syntax: `pricing pressure` matches both words (stemmed, so "pressures" also matches). `"supply chain"` is an exact phrase. `a OR b` matches either, `a NOT b` excludes, `NEAR(price increase, 10)` finds terms within 10 words, and `semicond*` is a prefix. Every passage keeps its section (for example "Item 1A. Risk Factors") and links to the filing on sec.gov.

The engine is SQLite FTS5 (BM25 ranking), which needs no extra installs. Semantic (embedding) search is the next step, as a re-ranking layer on top.

## Ask: cited research assistant (Rogo/Hebbia-style)

Open **Ask** in the web app and ask in plain English. It works across SEC filings, your data rooms, company financials, Form D funding rounds and precedent deals.

How it answers:
1. **Plan:** the model plans up to six lookups at once (one call, `effort: low`).
2. **Look up:** the lookups run in parallel against the local databases, in milliseconds to seconds.
3. **Write:** the model writes the answer with a `[n]` citation on every factual sentence.
4. **Verify:** every citation is checked. Document quotes must appear word for word in the cited passage. Data citations must match a value the lookup actually returned. Unverified citations are shown as such.

Click a citation to jump to its source card, which links to the SEC filing or opens the data-room document at the cited page. Scope a question to everything, public filings only, or one data room. Follow-up questions keep the conversation context.

The model can be set separately for Ask with `OM_MODEL_ASK`. With no model configured, Ask still runs the lookups and shows the matching sources without a written answer.

## Funding rounds (SEC Form D)

```bash
python3 open_multiples.py rounds load --last 8
```

```bash
python3 open_multiples.py rounds search --sort amount --equity-only
```

- `rounds load` loads the latest 8 quarters. Any quarter back to 2008 is available.
- `rounds search` searches and sorts the loaded rounds.
- The **Funding Rounds** page in the web app has filters, KPIs, capital raised by quarter, and a link to each filing.

**Categories:**
- **company** rounds (the default)
- **public_pipe**: listed companies placing shares privately
- **vehicle**: funds, credit vehicles, insurance separate accounts and evergreen offerings
- **real_estate**

Pooled funds and test filings are excluded. Amendments are merged into their original round no matter which order the quarters load in, with the latest amounts kept. Form D has no valuation field, and related people are counted but not named.

## Web app and data rooms (VDRs)

```bash
python3 open_multiples.py serve
```

Then open http://127.0.0.1:8765. The app has three pages:

- **Data Rooms:** create a room per deal and drag in files, whole folders, or a VDR export (`.zip`). You can also add a connector to keep the room in sync. Documents are listed by folder, and each one opens its original file.
- **Search:** search everything, public filings only, or one room. Every hit shows its page or section and opens the source.
- **Matrix:** build a documents × questions grid from a room. It comes with a diligence starter set: revenue, EBITDA, customer concentration, change of control and litigation.

**Supported files:** PDF (with page numbers, via poppler `pdftotext`; `brew install poppler`), Word, PowerPoint (including speaker notes), Excel (each sheet), HTML, text, CSV, JSON and email. Scanned PDFs without a text layer are flagged `needs_ocr`.

| Source | How to connect |
|---|---|
| Datasite, Intralinks, Ansarada, Firmex, DealRoom | Export the room as a `.zip` and drop it in, or run `room import`. The index-numbered folder tree is kept. Their APIs need partner agreements. |
| Box | Box connector (folder id), token in `BOX_ACCESS_TOKEN` |
| SharePoint / OneDrive | SharePoint connector (sharing link, or drive id + folder), Graph token in `MS_GRAPH_TOKEN` |
| Dropbox | Dropbox connector (folder path), token in `DROPBOX_ACCESS_TOKEN` |
| Anything synced to disk | Synced-folder connector (Box Drive, OneDrive, Dropbox, Google Drive for desktop). No token needed. |

How the connectors behave:
- Tokens live only in `.env`. The connector config stores the variable's name, never the token.
- A sync downloads only files that changed since the last sync.
- Files deleted at the source are reported but never deleted from the room.

The same operations from the command line:

```bash
python3 open_multiples.py room create "Project Falcon"
```

```bash
python3 open_multiples.py room import "Project Falcon" ~/Downloads/Falcon_VDR_export.zip
```

```bash
python3 open_multiples.py room connect "Project Falcon" --type synced_folder --set path="~/Library/CloudStorage/Box-Box/Project Falcon"
```

```bash
python3 open_multiples.py room sync "Project Falcon"
```

```bash
python3 open_multiples.py search '"change of control"'
```

The app binds to 127.0.0.1 and has no login yet. Don't expose it on a network until authentication is added.

## Sheets (Shortcut-style): spreadsheets wired to the data

Open **Sheets** in the web app and create a sheet from a template. The templates follow investment-banking modelling conventions; they are original layouts, not copies of any bank's own templates.

| Template | What's in it |
|---|---|
| **Trading comps** | Peers' size, growth, margins and Rule of 40, plus EV/Revenue, EV/EBITDA and P/E. Summary rows for max, 75th percentile, mean, median, 25th percentile and min. Implied EV for a target at the 25th percentile, median and 75th percentile. Sourced footnotes. |
| **Precedent transactions** | Deals and multiples from merger-proxy fairness opinions, with the same summary rows, the implied valuation of a target, and a source link for every deal. |
| **DCF** | WACC built with CAPM, an LTM base year from filings, a 5-year unlevered free cash flow build, a mid-year convention switch, and both terminal-value methods. Cross-checks: implied exit multiple, implied growth, and TV as a % of EV. Two live sensitivity tables: WACC × growth and WACC × exit multiple. |
| **LBO** | A paper LBO: entry and leverage, a debt-sweep operating model, exit, MOIC and IRR. |

Modelling conventions:
- **Colour code:** hard-coded inputs are blue, formulas are black, and values linked to data are green.
- **Inputs:** every assumption sits in a labelled input cell, with no numbers hidden inside formulas. A test enforces this.
- **Units and sources:** units are stated on every block, and footnotes give the source.

Data functions (green). Click a cell to see its source filing:
- `=OM("AAPL","revenue_ltm")` returns any public-comps field (see METHODOLOGY.md). `=OMNAME("AAPL")` returns the company name.
- `=MATRIX("falcon-diligence","1.1 CIM.docx","Revenue")` pulls a value from a data-room matrix into a model.

The engine supports `+ - * / ^ & %`, comparisons, `$` absolute references, ranges, and these functions: `SUM AVERAGE MEDIAN MIN MAX COUNT QUARTILE PERCENTILE IF IFERROR ROUND ABS SQRT POWER NPV AND OR NOT CONCAT LEN`. It catches cycles and errors, and fill-down (Ctrl+D) and fill-right (Ctrl+R) shift relative references.

**Export to .xlsx:** ordinary formulas stay live formulas in Excel, and data links are frozen to their values. CSV export is also available.

### Sheets agent

Click **✦ Agent** in Sheets and ask for changes in plain English. For example: "add EV/Sales and P/E columns with medians", "add a WACC × exit multiple sensitivity", "explain C42", "pull the CIM revenue from the Falcon matrix into B5".

How it works:
1. The agent sees the sheet: every cell's input and its computed value, your selection, the `=OM()` field catalogue and the available matrices.
2. It returns an edit plan. The server validates every reference, formula and data field.
3. The plan is applied to a **scratch copy** and calculated. Any formula error it produces (`#NAME?`, `#REF!`, a cycle, `#DIV/0!` and so on) goes back to the model for a fix, up to two rounds.
4. You see a **preview**, with changed cells outlined, and choose **Apply** or **Discard**.

The prompt carries the same modelling conventions as the templates: labelled inputs, no hard-codes, units, data functions instead of typed numbers, and standard summary statistics. The automatic checks and repair rounds are what make smaller models such as DeepSeek reliable here. Set the model with `OM_MODEL_SHEETS_AGENT`, or fall back to `OM_MODEL_DEFAULT`.

**No model needed** for the slash commands: `/comps AAPL MSFT NVDA`, `/dcf NVDA`, `/lbo AAPL` and `/precedents diagnostics` build the template models instantly.

## Deck Studio: storyboard → slide images → editable slides

The **Deck Studio** page runs the deck workflow as drawn:

1. **Storyboard.** Written as an MD (investment bank) or partner (strategy firm), from your brief and attached facts: SEC figures for tickers, figures from a data room, or facts you paste. Every number must come from those facts. The same persona critiques the storyboard and the writer revises it, before any slide is drawn.
2. **Slide prompts.** One per slide. Each asks for a strong visual and gives the exact title, labels and numbers, plus the layout, palette and type.
3. **Slide images.** An image model draws each slide as a picture, one at a time.
4. **Review / approval.** The partner/MD reviewer, or you if you pick "Me, one slide at a time", approves each picture or sends comments. Gemini redraws from the draft itself plus the comments. OpenAI redraws from the prompt plus the comments.
5. **Slides engine.** A vision model rebuilds the approved picture as an editable slide that matches it: native text, shapes, tables and charts (bar, line, pie, waterfall), with pictures cropped from the image only for illustrations. The words and numbers come from the storyboard, not from the picture.
6. **Review: correct?** The rebuilt slide is rendered and compared with the approved picture. Automatic checks also flag numbers missing from the slide or not in the storyboard, and text that overflows its box. Anything wrong goes back to the slides engine with comments.
7. **Output.** A .pptx, put through the consistency checker.

The reviewers hold the work to the partner/MD standard in `om/prompts/masterclass_slides.md`. That standard was distilled from 360 reviews in the earlier Costco runs, and later lessons are in `lessons_slides.md`.

| Stage (Settings) | Needs | Defaults |
|---|---|---|
| Storyboard | any text model | `OM_MODEL_STORYBOARD`, else the default model |
| Reviewer, slides engine | a vision model (Claude, OpenAI, Gemini, OpenRouter) | `OM_MODEL_SLIDE_REVIEW`, `OM_MODEL_SLIDE_BUILD` or `OM_MODEL_VISION`. A text-only default such as DeepSeek is skipped for these stages. |
| Image model | Gemini Nano Banana, OpenAI GPT Image, a gateway image model, or **any strong text model drawing the slide as SVG** | `OM_IMAGE_MODEL=gemini:gemini-nano-banana-2.1`, `openai:gpt-image-2.5-flare`, `custom:gpt-image-2`, or `svg:custom:gpt-6.1-terra` |

**Drawing slides as SVG** (`svg:<model>`) works through any gateway that only exposes chat endpoints:
- A text model draws each draft as SVG: exact words and numbers, real geometry.
- The draft is rendered to a picture locally with LibreOffice.
- Revisions edit the SVG source.
- The slides engine receives the SVG source alongside the picture, so the editable slide reproduces the design's exact positions.
- The SVG is sanitised before rendering: scripts, external links and embedded web content are removed.

One `GEMINI_API_KEY` covers all four stages. Runs are saved after every step in `data/studio/<id>/`, including every draft, layout, render and review, so a run can pause for your approval or be resumed after an error. The review renders need LibreOffice and poppler (`brew install --cask libreoffice; brew install poppler`).

### Grading: tough by design

Every review is done by a panel of two graders, a senior partner and an MD, scoring the work independently on the rubric dimensions used in the earlier Costco review loop. Spacing is a dimension on every page-level rubric.

- **Partner:** storyline, proof, visuals, craft, language, spacing.
- **MD:** accuracy, sourcing, valuation, honesty, polish, spacing.

The verdict is computed in code, not by the model:
- A page passes only when **both** graders sign off. Each needs an overall score of 8 or above, every dimension at 7 or above, and no blocking or major issue.
- Graders are calibrated against "a published bulge-bracket board book grades about 7". They never see the round number or earlier scores, so improving on a weak draft earns nothing.
- Automatic findings count as issues:
  - Numbers that don't match the storyboard: blocking.
  - Text overflowing its box: blocking.
  - A slide that couldn't be rendered for review: blocking.
  - Consistency-check findings: blocking or major.
  - Spacing-check findings: major.
- After the slides pass, the whole deck is graded once more, and any slide it flags goes back to the slides engine.
- A page that never clears the bar is labelled **not signed off** in the deck and on the page. It is never quietly passed.

The spacing check (`om/spacing.py`) flags:
- Content inside the 0.5" margin, or running off the slide.
- Body text under 14pt, or anything under 10pt.
- Overlapping boxes.
- Gaps other than 0.3" or 0.5", or both mixed on one slide.
- Edges that are nearly, but not exactly, aligned.
- "Equal" cards of unequal size, and card padding under 0.15".
- Cards that are mostly empty, and half-empty slides.
- Eyebrow labels.
- Across the deck: a missing title rule, footer rule or page number, and titles or footers that move between pages.

### House style, icons and components (built in)

`om/house.py` holds the grid, type scale, spacing, palette and visual grammar. The storyboard writer, image prompts, slides engine, components, spacing check and graders all read it.

The frame on every content slide:
- The title sits top-left, with **no eyebrow label** above it.
- A thin rule under the title.
- The measure and unit as a subtitle.
- The note and source line.
- A footer rule with the deck name on the left and the **page number** on the right.

`om/icons.py` ships 61 original line icons (people, money, growth, risk, logistics, data, ESG, and more) with keyword search. They are drawn as native PowerPoint vector shapes, so they stay sharp, recolour with the theme and need no downloads. Any SVG converts, so a larger open-source set can be added as-is.

`om/layout.py` components follow the house grid automatically. The slides engine prefers them over hand-placed shapes:
- `exhibit_frame`, `stat_callout`, `change_badge`, `takeaway_box`
- `process_flow` (numbered chevrons with icons), `icon_grid`
- `callout_card` (with a leader line), `numbered_heading`, `dot_plot`
- Tables with a highlighted column.

### Where API keys are kept

Keys entered in Settings go to the **macOS Keychain**: encrypted at rest and outside the project folder, so they can't be committed, zipped or shared with it. The app writes them through the Security framework directly, so a key never appears on a command line, in a temp file, in `.env`, in a log or on a page. Pages show only the last four characters.

On other systems, keys go to `~/.config/open-multiples/secrets.env` with owner-only permissions. Any key found in `.env` is moved out on startup.

The local web app is locked down:
- It listens on 127.0.0.1 only.
- It answers only to `localhost` / `127.0.0.1` host names, which blocks DNS rebinding.
- It refuses any change requested by another website open in your browser (Origin and Sec-Fetch-Site checks).
- Other sites can't frame its pages.
- Settings responses are never cached.

A gateway key is tied to the host it was entered for. If the base URL is changed (even by editing `.env` by hand), the key isn't sent until it's entered again. Keys are never sent over plain http except to localhost, and credentials embedded in URLs are refused.

### Using one OpenAI-compatible gateway

At the top of **Settings** you can enter a base URL and an API key for any OpenAI-compatible endpoint (e.g. MeshPool). **List models** shows the model IDs it offers. Then pick:
- a writing model for every text stage, such as a DeepSeek model;
- a vision model for the reviewer and the slides engine. It must be able to read images, which DeepSeek models can't.
- an image model, e.g. `gpt-image-2`, served through `{base}/images/generations`.

**Test writing** and **Test vision** confirm each model responds. The vision test sends a small image and asks for its colour.

## Consistency check: decks, models and data rooms

The **Check** page (or `check` on the command line) reads every number in a deck, workbook or data room as a *fact*: metric, company, period, value, displayed precision, and where it came from. It then looks for inconsistencies:

| Check | Example it catches |
|---|---|
| Same figure, different value | "FY2026 free cash flow $9.39B" on slide 2, "$9.38B" on slide 3; CIM says 415 customers, model says 412 |
| Totals and medians | the table's Median row shows 17.9% but the rows above give 16.5% |
| Sums written in the text | "$15.82B operating cash flow less $6.43B capex left $9.38B" (that comes to $9.39B) |
| Margins and growth | "Adjusted EBITDA $19.5m, a margin of 22%" on $84.2m of revenue (that's 23.2%) |
| Bridges and waterfalls | the bars before "Closing cash" don't add up to it |
| SEC tie-out | a company's revenue or margin doesn't match its 10-K / 10-Q (LTM or fiscal year) |
| Workbooks | `#N/A` / `#DIV/0!` cells, failing rows on a Checks tab, the same line disagreeing across sheets |
| Units | one metric in $m on one slide and $bn on another |

To stay quiet when nothing is wrong, it follows these rules:
- **Precision:** figures are compared at the precision they're displayed, so 84.2 vs 84.23 is fine, but 9.39 vs 9.38 is flagged.
- **Periods:** figures for different periods are never compared.
- **Ambiguous numbers are skipped:** a number needs its metric right next to it, and option outcomes ("the $4B buyback leaves $15.5B of cash"), shares ("41% of revenue"), increments ("add $6m"), multi-year CAGRs and dates are all left out.
- **Speaker notes are ignored by default,** because the reader never sees them.

On the seven Costco board decks from the earlier review loop, it raised 4 flags, all of which the partner and MD reviewers had also raised.

```bash
python3 open_multiples.py check deck.pptx                       # deck, tied to SEC filings
python3 open_multiples.py check model.xlsx                      # workbook (recalculated with LibreOffice if needed)
python3 open_multiples.py check "Project Falcon" --room         # every document in a data room
python3 open_multiples.py check deck.pptx --against-room "Project Falcon"
```

Rules only, by default. With an AI model set for the `check` stage, it also pulls figures from harder prose (each one must quote its passage word for word) and reviews each mismatch for differing definitions, such as gross vs net or reported vs adjusted. If the model judges two figures to measure different things, that mismatch is downgraded.

## Slides: client-ready PowerPoint from the data

Every deck is a native, editable `.pptx` (real PowerPoint tables and charts, not pictures), with a source line on every slide and a methodology page. Numbers come from the filings or the model; takeaways are computed from the data, not written by a model.

| Deck | Where | What's in it |
|---|---|---|
| Trading comps | Sheets → **Slides** (comps sheet, or type several tickers) | Comps table with median and mean, KPI strip, growth vs. EBITDA margin chart (banks and insurers left out, with a footnote), scale chart, takeaways |
| Company profile | Sheets → **Slides** (type one ticker) | KPI tiles, FY-1 / FY / LTM financial summary, revenue and EBITDA chart, the most specific risk factors quoted from the latest 10-K |
| Valuation | Sheets → **Slides** on a DCF sheet | Football field (base case ± one sensitivity step), assumptions and outputs, sensitivity grid. If the two methods don't overlap, the page says so and shows the implied growth / multiple cross-checks |
| Funding market update | Funding Rounds → **Export slides** (uses your filters) | KPIs, capital raised by quarter, largest rounds, capital by industry |
| Research note | Ask → **Export to slides** under an answer | The answer with citation markers, plus a sources appendix with verbatim quotes (or the sources found, when no model is set) |

Set the firm name printed on covers and footers in **Settings → Slides**. From the command line:

```bash
python3 open_multiples.py deck comps AAPL MSFT NVDA GOOGL
python3 open_multiples.py deck tearsheet AAPL
python3 open_multiples.py deck rounds --industry Biotechnology
```

Decks are written to `data/out/` (or `--out file.pptx`). They open in PowerPoint, Keynote and Google Slides.

## AI models: model-agnostic, routed per stage

Every AI call goes through one router, so any provider works and each stage can use a different model, tuned later for cost and quality. Set them in `.env`:

```
OM_MODEL_DEFAULT=deepseek:deepseek-chat         # all stages
OM_MODEL_MATRIX=deepseek:deepseek-chat          # per-stage override
OM_MODEL_SHEETS_AGENT=anthropic:claude-opus-5-5
DEEPSEEK_API_KEY=...
```

```bash
python3 open_multiples.py models
```

`models` shows which model serves each stage.

**Supported providers:**
- Claude (official SDK)
- DeepSeek, OpenAI, OpenRouter, Groq, Together, Fireworks and Mistral
- local Ollama
- any OpenAI-compatible server, via `OM_PROVIDER_<NAME>_BASE_URL`

**Why any model works well:**
- **Structured output everywhere:** JSON-schema output where the provider supports it; otherwise JSON mode with the schema in the prompt.
- **Validation and repair:** every reply is checked against the schema, with one automatic repair retry.
- **Caching:** the document goes first in each request, so it's cached explicitly on Claude and automatically by DeepSeek and OpenAI prefix caching.
- **Model-independent grounding:** every quote is matched against the source text no matter which model answered, so a cheaper model can't slip in unsupported claims.

## Matrix (Hebbia-style): documents × questions with cited answers

**No API key needed.** Without a key, the Matrix runs an *extractive* engine. Each cell quotes the best-matching passage verbatim, with its page, and numeric columns get a parsed value. Cells are labelled "extracted". If you add `ANTHROPIC_API_KEY` later, the next `run` upgrades those cells to written answers. The engine is chosen automatically, or set it with `--engine`.

Each row is a filing and each column is a question. Claude answers every cell from that document only. Each answer cites the passage it came from and a verbatim quote, and the quote is then checked against the filing text. Cells whose quote isn't found are flagged **unverified**, so nothing unsupported is shown as fact.

Setup, once:

```bash
pip install -r requirements.txt
```

Then add `ANTHROPIC_API_KEY=...` to `.env`.

```bash
python3 open_multiples.py matrix create ai-capex --query '"capital expenditures"' --form 10-K 10-Q --max-rows 10 --column "Capex:currency::What were capital expenditures in the period?" --column "AI spend::What does the company say about AI infrastructure investment?"
```

```bash
python3 open_multiples.py matrix run ai-capex
```

```bash
python3 open_multiples.py matrix add-column ai-capex --column "Guidance::What capex outlook does management give?"
```

```bash
python3 open_multiples.py matrix show ai-capex
```

```bash
python3 open_multiples.py matrix export ai-capex
```

- `create` builds the grid from a search.
- `run` fills every empty cell (`--effort low|medium|high`).
- `add-column` adds a question; the next `run` asks only that column.
- `show` prints the grid; `export` writes `data/out/matrix_ai-capex.csv` with answers plus their quoted sources.

The same features are in the web UI (`serve`, then **Matrix** in the header). Click any cell to see its quotes, whether each one was verified, the 10-K section it came from, and a link to the filing.

How it works:
- **Retrieval:** large filings are cut to the passages relevant to the questions. A 242k-character 10-K becomes about 23k.
- **One call per row:** each row is a single Claude call (`claude-opus-5-5`, structured JSON output). The document is sent as a cached prefix, so adding columns later is cheap.
- **Refusal fallback:** server-side refusal fallback is on (`fallbacks: "default"`). A request the model declines is re-run on a fallback model rather than failing.
- **Usage report:** each run reports token usage, including cached tokens.

## Prices

Free price feeds (Yahoo/yfinance, Alpha Vantage free, Tiingo Starter, Stooq) are personal-use only, so none is wired in. You have two options:

- `--prices file.csv` with the columns `ticker,date,close,currency,ordinary_per_unit`, from your licensed EOD source. `ordinary_per_unit` is the ADR ratio and defaults to 1.
- `--twelvedata` with `TWELVEDATA_API_KEY` in `.env`. Their business tier allows displaying derived metrics with attribution; get that confirmed in writing.

`tests/fixtures/test_prices.csv` holds **placeholder** prices (100.00) for tests only.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Layout

```
om/sec.py        SEC client: rate limit, retries, resumable downloads, raw store with SHA-256
om/concepts.py   XBRL tag chains per metric
om/facts.py      FY / LTM / point-in-time / restatement logic
om/metrics.py    fields, EV bridge, multiples, n/m rule, provenance
om/fx.py         ECB reference rates (Frankfurter primary, ECB zip fallback), pegs
om/prices.py     CSV and Twelve Data price providers
om/net.py        resumable HTTP GET
om/pptx.py       PowerPoint writer: native tables and charts, theme, master/layout
om/decks.py      deck builders (comps, profile, valuation, funding market, research note)
om/studio.py     Deck Studio pipeline (storyboard, image drafts, reviews, slides engine)
om/layout.py     layout JSON -> native PowerPoint (the slides-engine contract), PNG crop, LibreOffice render
om/images.py     image models (Gemini Nano Banana, OpenAI GPT Image)
om/consistency.py inconsistency checker: facts from decks, workbooks and rooms; conflicts, footing, math, SEC tie-out
```

## Roadmap

These follow the build plan in the research report:

1. Monthly history snapshots back to 2016, gated on filing dates.
2. An estimates layer: 8-K guidance, broker PDFs (Saudi Arabia and Qatar first) and model estimates, each labelled.
3. M&A multiples from merger-proxy precedent tables (DEFM14A / S-4).
4. Funding rounds from Form D and UK SH01 filings.
5. Your own taxonomy (seeded from SIC/NAICS, classified with an LLM).
6. EU/UK (filings.xbrl.org), then Saudi Exchange XBRL.
7. A REST API, MCP server and Excel add-in.
