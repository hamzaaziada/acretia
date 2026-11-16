# Company data sources: UK/EU first (desk research, 2026-11-16)

Public web only. Labels: [official], [vendor claim], [independent], [inference]. Mark anything unconfirmed **UNVERIFIED**. Prices are indicative. This is not legal advice: read each primary set of terms before integrating.

## 1. Free official sources (integrate first)

| Source | What it provides | Terms | Limits / coverage |
|---|---|---|---|
| **UK Companies House REST API** | Profile, filings, officers, PSC, charges; accounts via the Document API ([overview](https://developer.company-information.service.gov.uk/overview)) | OGL v3.0 for content "except where otherwise stated"; data-protection law still applies ([products](https://www.gov.uk/guidance/companies-house-data-products)) | Free; 600 req / 5 min ([guidelines](https://developer.company-information.service.gov.uk/developer-guidelines)); all UK companies |
| **CH bulk accounts data (iXBRL)** | Daily and monthly ZIPs of iXBRL instances: **the best structured UK financials** ([download](https://download.companieshouse.gov.uk/en_accountsdata.html)) | No licence stated on the page | Free. Covers about 60–75% of filers (the two official figures conflict). Coverage rises as software filing becomes mandatory (reported for April 2028) |
| CH bulk company data and PSC | Monthly CSV of live companies; PSC JSON | Free | — |
| CH streaming API | Real-time changes | Terms UNVERIFIED | Free |
| **ESEF via [filings.xbrl.org](https://filings.xbrl.org/)** | 27,669 ESEF/iXBRL filings of listed issuers, 28 country codes (no DE seen) | Page shows "© XBRL"; API terms UNVERIFIED (the filings themselves are public) | Free; listed issuers only |
| **GLEIF LEI** ([download](https://www.gleif.org/en/lei-data/gleif-concatenated-file/download-the-concatenated-file)) | Who is who and who owns whom (678,949 relationship records); entity-resolution spine | Terms linked; CC0 UNVERIFIED | Free bulk and API; no financials |
| **France INPI RNE** ([API/FTP](https://www.inpi.fr/acces-aux-api-et-ftp-data-inpi)) | Daily XML/CSV; non-confidential annual accounts since 2017 | Free reuse licence (Etalab? UNVERIFIED) | Many SMEs keep their accounts confidential |
| **Netherlands KvK open dataset** ([KvK](https://www.kvk.nl/en/ordering-products/kvk-financial-statements-open-data-set/)) | Annual-account XML bulk and JSON API (anonymised, partial) | CC-BY 4.0 ([data.overheid.nl](https://data.overheid.nl/dataset/kvk-jaarrekeningen-open-data-set)) | Free; paid Handelsregister APIs at €0.02/query |
| **Norway Brønnøysund** ([dataset](https://data.norge.no/en/datasets/7c87f169-2520-4e56-ba2a-b7a3cc7de2e9/regnskapsregisteret)) | Structured accounts API (a "preview", may be shut down without notice) | NLOD for core registers; accounts API licence UNVERIFIED | Free, fragile |
| **Ireland CRO** open data ([CRO](https://cro.ie/the-companies-registration-office-cro-announces-the-launch-of-new-open-data-portal/)) | Bulk and API | CC BY 4.0 | Images of financial statements are paid (from €2.50) |
| Germany Unternehmensregister / Bundesanzeiger | Accounts as PDF/HTML; no public API | Registration for accounts; terms on mass queries UNVERIFIED | **The biggest gap**: no structured data |
| Spain BORME / Registro Mercantil | BORME open API (mostly PDF); accounts €6–15 each | UNVERIFIED | — |
| Denmark CVR, Italy, EU BRIS | UNVERIFIED | | |

EU Implementing Regulation 2023/138 makes company and ownership data a free high-value dataset ([data.europa.eu](https://data.europa.eu/en/news-events/news/unlocking-potential-high-value-datasets-impact-hvd-implementing-regulation)). National compliance is patchy, and whether it covers financial statements is UNVERIFIED.

## 2. Cheap paid sources (need the user's approval to buy)

| Vendor | Price signal | Note |
|---|---|---|
| Pappers (FR) | Credits, from about €20/month (UNVERIFIED); has an MCP | Best-value French private financials; check display rights |
| North Data (DE) | API price not public; web from €49/month | Fills the German gap |
| KvK paid API | €0.02/query | NL beyond the open set |
| Bigdata.com (RavenPack) | Pro $40/month plus per-token usage; example runs $0.57–$1.82 ([pricing](https://bigdata.com/pricing)) | Most startup-friendly "content for agents": transcripts, news, filings |
| OpenCorporates | £2,250/yr for 500 calls/month ([pricing](https://opencorporates.com/pricing/)) | Entity matching only |
| FMP | Display/redistribution rights reportedly from $333/month | Verify in writing |
| Endole, Creditsafe (~$25.8k/yr median), Crunchbase (~$30k), Dealroom (~€12.5k), Tracxn | Various | Mostly internal-use licences |
| Orbis/BvD, D&B, PitchBook ($24–32k/seat), Preqin | Expensive | Skip until a customer pays for them |

Rule: if vendor data shows up inside Acretia outputs, an "internal use" licence isn't enough. Get written display and derived-data rights.

## 3. Expert-interview content (the Tegus angle)

- **Tegus and Stream** now belong to AlphaSense (Tegus for $930m in 2024): competitor assets.
- **Third Bridge:** licenses to platforms via MCP (100k+ transcripts; partners include Hebbia, July 2025) ([partnerships](https://www.thirdbridge.com/en-us/data-solutions/partnerships)). **The #1 partnership target.**
- **Arbolus:** public REST API with transcript retrieval ([docs](https://api.arbolus.com/docs/index.html)). Developer-friendly; a mid-market candidate.
- **Guidepoint and GLG:** MCP connectors that use the customer's own entitlements; not corpus licences.
- **In Practise, Inex One:** smaller or aggregator; API terms UNVERIFIED.
- **Building our own library:** about $1,000 per call all-in, so ~$0.5m for 500 calls. We can't match the incumbents' breadth, so go narrow (MENA, UK mid-cap). That needs our own MNPI and compliance regime (cost UNVERIFIED).

## 4. Earnings calls and IR content

The primary source is company IR pages and webcasts. Facts aren't protectable, but verbatim transcripts probably are. Analysing and briefly quoting is fine; republishing full text isn't. Paid transcript APIs (API Ninjas, FMP) need redistribution checks.

## 5. Scraping: the legal position

- **EU database right and contract:** *Ryanair v PR Aviation* (C-30/14) lets site terms restrict use even where the data is unprotected. Terms are the main hazard.
- **Text and data mining:** DSM Art. 4 allows commercial TDM unless rights are reserved in machine-readable form. Hamburg (Dec 2025) held that only machine-readable reservations count. The **UK** has no commercial TDM exception (government decision, March 2026).
- **GDPR:** directors and shareholders are personal data. Legitimate interest can work, with minimisation and an opt-out; a 2026 CJEU ruling limits unconditional access to shareholder data (citation UNVERIFIED).
- **US:** *hiQ v. LinkedIn* says CFAA doesn't cover public pages, but the contract risk remains.

**Do:**
- use official APIs and bulk files first;
- log the site terms you reviewed, with dates;
- honour robots.txt and TDM reservations;
- rate-limit, and identify the bot;
- store facts, not narrative text;
- minimise personal data;
- get written rights from paid vendors.

**Don't:**
- scrape against a site's terms;
- bypass logins, paywalls or CAPTCHAs;
- bulk-copy copyrighted transcripts or reports for commercial AI use;
- build profiles of individuals;
- resell raw register data under a licence nobody has read.

## 6. Recommendations

**(a) Integrate now (free):**
1. Companies House API + bulk iXBRL accounts.
2. ESEF (filings.xbrl.org).
3. KvK open set, INPI RNE, Brønnøysund.
4. GLEIF.
5. CRO.

These reuse our XBRL/iXBRL pipeline. UK/EU private-company financials are weak at Rogo, Hebbia and AlphaSense, so this is a real differentiator [inference].

**(b) Buy first, with the user's approval:** Pappers (FR), North Data or the KvK paid API (the DE/NL gap), and Bigdata.com Pro (transcripts and news for agents).

**(c) Partner:** Third Bridge (the Hebbia playbook), Arbolus, Guidepoint/GLG as customer connectors, Daloopa/Fiscal.ai only for non-US KPIs, and a MENA-focused expert network.

**Strategic read [inference]:** incumbent data vendors now ship MCP servers, so data access alone won't differentiate. The defensible position is **normalised UK/EU/MENA private-company financials** that incumbents haven't built, plus one licensed qualitative feed.

**Gaps still open:** Denmark CVR, Italy, BRIS, CH streaming terms, the GLEIF licence text, Motley Fool and FMP terms, AI-use clauses, MNPI costs.
