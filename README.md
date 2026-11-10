# Lead Intelligence Engine

**Evidence-led prospect research and qualification for CRM and AI-automation opportunities.**

Built for [VertexData Systems](https://vertex-data-system.vercel.app/), this project is designed to produce fewer, better-understood prospects rather than maximize raw lead volume.

For each company, the workflow aims to establish:
- Company identity, location, size, and relevant business signals
- Publicly available contact and decision-maker information
- Source evidence and confidence for important facts
- A reasoned fit assessment for CRM or automation services
- A practical, research-backed outreach angle

Unknown or conflicting details are marked for review instead of being silently guessed.

> **Compliance first:** Read the [Compliance notes](#compliance-notes) before using live sources. The project intentionally avoids unsupported or prohibited scraping approaches and documents alternative research methods.

---

## Quick start (no API keys needed)

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m app initdb
python -m app demo
```

`demo` runs the **real** pipeline — real scoring, real verification logic, real Excel
formatting — against six clearly-labeled synthetic companies (every name ends in
"(Demo)"), so you can open `exports/MASTER_VERIFIED_LEADS.xlsx` and see exactly what the
system produces before wiring up a single API key. The demo fixtures are deliberately
built to land in every possible outcome bucket:

| Demo company | Lands in | Why |
|---|---|---|
| Riverstone Roofing & Exteriors | MASTER | Strong, cross-verified signals |
| Bluepeak HVAC Solutions | REJECTED | CRM score below your configured threshold |
| Homestyle Cleaning Co | NEEDS_REVIEW | Employee count couldn't be determined — not guessed |
| Apex Legal Group | NEEDS_REVIEW | Two sources disagree on the phone number |
| Old Mill Hardware | REJECTED | Marked permanently closed |
| TinyDesk Bookkeeping | REJECTED | Confirmed outside your employee-count range |

The 6 per-source files (`GOOGLE_MAPS_LEADS.xlsx`, etc.) are empty in demo mode — demo
data isn't tied to a real connector. Everything else (MASTER, NEEDS_REVIEW, REJECTED,
COLD_CALL_PROSPECTS, RUN_REPORT) is fully populated.

---

## Compliance notes — read this first

Every source in the original brief is implemented as an honest, self-reporting
connector — see `python -m app sources` for the live list. Four tiers:

| Tier | Meaning |
|---|---|
| **AVAILABLE** | Works right now through a compliant, official method |
| **LIMITED** | Works, but with real restrictions you need to know about |
| **OPTIONAL** | Not on by default; can be enabled later via an official API or licensed provider |
| **UNAVAILABLE** | No compliant/free method exists right now — ships as a documented interface, not a fake implementation |

```
NAME             AVAILABILITY SUMMARY
google_places    AVAILABLE    Official Places API (New). Name/address/phone/website/rating/status.
website          AVAILABLE    Fetches a prospect's OWN public site. Not third-party scraping.
google_search    LIMITED      Official Custom Search API — closed to new signups since 2026, retiring 2027-01-01.
meta_ads         LIMITED      Official Ad Library API — for US ads, only indexes political/issue ads.
facebook_pages   LIMITED      Official Graph API — only Pages you already manage or have App Review for.
linkedin         UNAVAILABLE  No compliant scraping method exists. See app/connectors/linkedin.py.
```

### Why LinkedIn isn't a scraper

LinkedIn's User Agreement prohibits automated data collection — **including public
pages**; "public" doesn't change the contract you agreed to by using the site. This is a
Terms-of-Service issue, separate from and in addition to any CAPTCHA/login-bypass
concern (your own brief already correctly said not to bypass those — this is the other
rule, the one about not scraping at all). LinkedIn continues to actively sue scraping
operations (most recently in October 2025) and to suspend accounts/IP ranges associated
with automated collection. Building a scraper here would create real legal and
account-suspension exposure for VertexData for no durable technical advantage — LinkedIn
also keeps changing its anti-automation defenses, so a scraper built today tends to break
within weeks regardless.

**What to use instead**, cheapest/most manual to most turnkey:
1. Manual research — a human looks up the company/decision-maker and copies what's needed.
2. LinkedIn Sales Navigator, used manually within its own terms.
3. A properly licensed third-party B2B data provider (ZoomInfo, Apollo, or similar) that
   has its own data-sourcing agreements — this is the "optional future integration" your
   original brief already anticipated for tools like these. Wire one in as a new
   connector; the `RawLead` shape (`app/connectors/base.py`) will accept whatever it
   returns without changing anything else in the pipeline.

### Why Meta/Facebook aren't general scrapers either

Meta's Terms of Service prohibit automated collection from Facebook/Instagram without
prior permission, the same principle as LinkedIn above. Two connectors are implemented
against Meta's own *official* APIs instead:
- **`meta_ads`** uses the public Ad Library API (built by Meta specifically for ad
  transparency queries — not a scraper). As of 2026, for `ad_reached_countries=US` it
  only indexes political/social-issue ads; ordinary commercial ads are only covered when
  the ad ran in a UK/EU country. For your stated US ICP, expect this to mostly come back
  empty — that's Meta's restriction, not a bug here. It becomes a real channel if/when you
  expand to the UK/EU.
- **`facebook_pages`** uses the Graph API, but only for Pages you already manage (via a
  Page Access Token) or that Meta App Review has approved your app for. It cannot
  discover new prospect Pages — pass it a Page ID you're entitled to query, not a search
  term.

### Why Google Search is effectively unavailable for a new build

Google's Custom Search JSON API was closed to new customers in 2026 and is being fully
discontinued on **2027-01-01**. The connector is fully implemented and will work if you
already have a pre-existing key, but there's no way to sign up for one fresh right now.
**Google Places + website enrichment are your primary Google-side discovery channels.**
Scraping google.com/search directly is also a Terms-of-Service violation independent of
this API's status, so that was never on the table either.

### The website-enrichment connector is different, on purpose

Fetching a prospect's own public marketing site (their homepage, `/about`, `/contact`,
etc.) is standard, low-risk web fetching of a business's own published content — nothing
like scraping a third-party platform's user data. It respects `robots.txt` and a shared
rate limiter (`REQUEST_DELAY_SECONDS` in `.env`), and never fetches anything that resolves
to a private/internal IP address (SSRF guard in `app/utils/validators.py`). This is
deliberately the strongest signal source in the system.

### A note on outreach itself

Once you have verified contacts, cold email in the US is governed by CAN-SPAM (opt-out
mechanism, accurate headers, physical address) and cold calling/texting by the TCPA
(check do-not-call and consent rules, especially for texts). This project doesn't send
anything — it only assembles who to contact and what to say — but worth knowing before
your team acts on `COLD_CALL_PROSPECTS.xlsx`. This isn't legal advice; check with counsel
if you're scaling outreach meaningfully.

---

## Architecture

```
lead-intelligence-engine/
├── app/
│   ├── core/            # config loading, logging, database engine/session
│   ├── models/          # SQLAlchemy schema (10 tables)
│   ├── connectors/      # one file per source + the registry + search-term templates
│   ├── enrichment/      # website_analysis.py — the strongest signal source
│   ├── verification/    # status computation + final master/needs_review/rejected gate
│   ├── deduplication/   # domain > phone > (name+city) merge logic
│   ├── scoring/         # CRM Opportunity Score + Data Quality Score
│   ├── coldcall/        # brief + opening generation, optional LLM polish
│   ├── exports/         # every Excel file
│   ├── utils/           # normalization, SSRF guard, rate limiting, evidence-merge helper
│   ├── pipeline.py       # orchestrates every stage
│   └── cli.py            # `python -m app <command>`
├── tests/                # 107 tests, no network required
├── config/config.yaml    # targeting & scoring knobs
├── .env.example          # secrets & API keys (copy to .env)
├── data/{raw,processed,verified,rejected}/  # audit JSON snapshots per run
├── exports/              # every .xlsx + RUN_REPORT.json land here
└── demo_output/          # a pre-generated sample run, so you can look before running anything
```

### Pipeline order

```
DISCOVER → NORMALIZE → ENRICH → DEDUPLICATE → VERIFY → SCORE → GENERATE BRIEFS → FILTER → EXPORT
```

This reorders two stages relative to a literal discover→normalize→verify→enrich→
deduplicate→score reading of the brief, for a concrete reason: enrichment adds the
second-source evidence that deduplication and verification actually need to compare, and
records from different connectors should be merged into one canonical company *before*
verification/scoring run — otherwise you'd score fragments and immediately redo it after
merging anyway. Every other guarantee holds: one connector's failure never stops the run,
and nothing reaches an export without going through real verification and scoring.

### Database (10 tables)

`companies`, `contacts`, `sources`, `source_records`, `company_signals`, `lead_scores`,
`verification_results`, `crawl_runs`, `errors`, `exports` — see
`app/models/models.py` for the full schema and comments on why each exists. SQLite by
default (`data/leads.db`, zero setup); set `DATABASE_URL` in `.env` to point at Postgres
instead — nothing else needs to change.

---

## Scoring methodology

Two **independent** 0–100 scores, on purpose — see `app/scoring/scoring.py`:

- **CRM Opportunity Score** — "how likely is this company to benefit from CRM/automation?"
  Business Size Fit (15) + Lead Generation Activity (15) + Advertising Activity (10) +
  Sales Complexity (15) + Customer Follow-Up Need (15) + Digital Presence (10) +
  Automation Opportunity (10) + Evidence Quality (10). Bands: 90+ HOT, 80+ VERY HIGH,
  70+ HIGH, 60+ MEDIUM, below 60 LOW.
- **Data Quality Score** — "how trustworthy/complete is what we have?" Ten checks
  (company traceability, website reachability, phone/email/owner verification,
  employee-count confidence, location, industry, source traceability, no-duplicate),
  10 points each.

A company can be CRM=95 / Quality=60 — an excellent prospect that still needs manual
verification before you call. The two numbers are never combined, and neither one is
ever computed from a guess: verification statuses (`Verified` / `Publicly Listed` /
`Conflicting` / `Unverified` / `Not Found`) come from *counted, recorded evidence*
(`app/utils/merge.py`), never from "this looks plausible."

**Employee count** is the weakest-populated field in a fully-compliant build — the two
richest sources for it (LinkedIn company pages, paid B2B databases) are exactly the ones
this project won't scrape. When it can't be confidently determined, the lead goes to
`NEEDS_REVIEW` rather than getting a guessed number or an automatic rejection.

---

## Configuration

- **`config.yaml`** — geography, employee-count range, score thresholds, which
  industries to search (`ALL` runs every key in `app/connectors/search_terms.py`), and
  which connectors are on. `facebook_pages` and `linkedin` default to **off**.
- **`.env`** (copy from `.env.example`) — API keys and crawl timing. Every key is
  optional; a missing one just makes that connector report itself unavailable and the
  run continues with what *is* configured.

Getting keys:
- **Google Places**: [console.cloud.google.com/google/maps-apis](https://console.cloud.google.com/google/maps-apis/api-list) → enable "Places API (New)". Has a modest free monthly allowance, then usage-based billing — Google has changed this pricing more than once, check their current Maps Platform page.
- **Google Custom Search**: only relevant if you already have a pre-2026 key — see Compliance notes above.
- **Meta Ad Library**: [facebook.com/ads/library/api](https://www.facebook.com/ads/library/api/) — requires a Meta developer app with identity verification.

---

## CLI

```bash
python -m app initdb                                   # create tables
python -m app sources                                   # list every connector + tier
python -m app demo                                       # full pipeline on synthetic data
python -m app pipeline --industry roofing --location "Texas"   # full run, end to end
python -m app discover --source google_places --industry hvac --location "Dallas, TX"
python -m app enrich          # website-enrich anything not yet checked
python -m app verify          # recompute verification statuses
python -m app deduplicate     # merge duplicate records
python -m app score           # recompute both scores
python -m app export          # classify current data + write every Excel file
```

`pipeline` and `demo` run everything end to end in one call. The granular commands
operate on whatever's already in the database — handy for re-running one stage after
tuning `config.yaml` without repeating the others.

---

## Testing

```bash
pip install -r requirements.txt
pytest tests/ -v
```

107 tests, all offline (no network, no real API keys) — pure-logic tests for
normalization/validation/scoring/deduplication, HTML-parsing tests against static
fixtures for the website-enrichment signals, and one full end-to-end test that runs the
real pipeline against demo data in an isolated temp database. That last test is a
regression guard for a real bug caught by hand while building this: an early version let
a low CRM score silently reject a lead even when the actual issue was an *unresolved*
one (unknown employee count, conflicting sources) that should route to `NEEDS_REVIEW`
instead. `tests/test_verify.py::TestClassifyLeadTiering` exists specifically so that
doesn't come back.

---

## What's not included in this pass

- **A FastAPI/REST layer** — the original stack list mentioned FastAPI; this ships as a
  CLI instead (`python -m app ...`), which fits a batch pipeline tool well and was enough
  to deliver a genuinely complete, working system in the time available. The data layer
  (SQLAlchemy models in `app/models/models.py`) is ready to sit behind a thin FastAPI
  wrapper later — nothing about the pipeline itself would need to change.
- **A Postgres-specific test** — the code is Postgres-ready (`DATABASE_URL`), but only
  SQLite has actually been exercised here.
- **Playwright / JS-rendered sites** — the website connector uses `requests` +
  BeautifulSoup, which covers server-rendered marketing sites (the large majority of SMB
  websites). A heavy JS single-page-app site would need a headless-browser connector;
  the interface is ready for one, it just isn't built.
- **A live dashboard** — `RUN_REPORT.xlsx`/`.json` cover the same metrics a dashboard
  would show; a `dashboard/` folder with a minimal static viewer is included as a
  starting point rather than a full app.
- **LinkedIn / general Facebook-page discovery** — by design, see Compliance notes.

## Extending it

To add a new source (e.g. a licensed B2B data provider as a LinkedIn-equivalent):
1. Subclass `BaseConnector` in a new file under `app/connectors/`, implement `discover()`
   returning a list of `RawLead` (`app/connectors/base.py`), and set `availability` +
   `capability_summary` honestly.
2. Register it in `app/connectors/registry.py`.
3. Add a toggle for it in `config.yaml` under `sources:`.

Nothing else in the pipeline needs to change — normalization, dedup, verification,
scoring, and export all operate on the common `RawLead`/`Company` shape.


---

## Streamlit dashboard

The project includes a professional, minimal Streamlit workspace in `dashboard/app.py`.
It uses the existing database, connector registry, pipeline, verification, scoring, cold-call, and export layers — it does not generate fake lead data.

### Start the dashboard

```bash
# Windows PowerShell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m app initdb
streamlit run dashboard/app.py
```

Open the local Streamlit URL shown in the terminal (normally `http://localhost:8501`).

### Dashboard areas

| Area | What it does |
|---|---|
| Dashboard | Pipeline metrics, source/industry/state breakdowns, demo run, refresh |
| Lead Discovery | Connector-based discovery and full-pipeline controls |
| Leads | Search, filters, lead table, company profile and evidence |
| Verification & Scoring | Re-run enrichment, deduplication, verification, scoring and export; regenerate cold-call briefs |
| Cold Call Prospects | Review recommended opening and generated call brief |
| Exports | Download runtime Excel/JSON/CSV outputs and shipped demo outputs |
| System Status | Database health, connector status, runtime paths |
| Settings | Targeting configuration and credential status without exposing secrets |

### Design

The dashboard is intentionally blue/white, minimal, and B2B-oriented. Secrets are never displayed in the UI. Keep real keys in `.env`, which is ignored by Git.

---

## Recommended `.env` setup

For the current Google Places + Exa + Grok configuration:

```env
GOOGLE_PLACES_API_KEY=your_google_places_key
EXA_API_KEY=your_exa_key
LLM_PROVIDER=xai
XAI_API_KEY=your_xai_key
XAI_MODEL=grok-4.7
```

Leave optional/unused providers blank until you intentionally enable them.

---

## GitHub push

After downloading/extracting this project, run these commands from the project root:

```powershell
git init
git branch -M main
git remote add origin https://github.com/Ismailshah-123/lead-scrapper.git
git add .
git commit -m "Build professional lead intelligence dashboard"
git push -u origin main
```

If the local repository already has a remote named `origin`, use:

```powershell
git remote set-url origin https://github.com/Ismailshah-123/lead-scrapper.git
git add .
git commit -m "Build professional lead intelligence dashboard"
git push -u origin main
```

Before pushing, confirm that `.env` is ignored:

```powershell
git status
```

Your API keys should **not** appear in the staged files.
