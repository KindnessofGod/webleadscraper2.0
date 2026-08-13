# Nigeria Business Lead-Gen Pipeline

Scrapes local business listings from Google Maps across Nigerian cities,
filters out businesses that already have a website, scores the rest for
likely ability/need to buy a ₦150k-250k website, tags each by niche, and
exports a deduplicated CSV list ready for outreach.

Built around one hard constraint: **the pilot budget is ~$5**. Every stage
is designed so a bug can't quietly burn through it -- see "Cost guardrails"
below.

## How it works

| Stage | What it does | File |
|---|---|---|
| A | Grid-search Google Maps via Playwright + a residential proxy (Webshare free tier or DataImpulse paid) | `src/scraper.py`, `src/grid.py`, `src/proxy.py` |
| B | Free check: does the Maps-listed `website` field actually resolve? | `src/qualify_tier1.py` |
| C | Cheap check: one live search-API query per remaining lead | `src/qualify_tier2.py` |
| D | Score niche fit / review signal / rating into hot-warm-cold | `src/scoring.py` |
| E | Normalize niche, dedupe, export CSV | `src/niche.py`, `src/dedup.py`, `scripts/export_by_niche.py` |
| F | Structured JSON-lines logging, checkpointed resume, cost ledger | `src/logging_setup.py`, `src/db.py`, `src/cost_tracker.py` |

Everything lives in one SQLite file (`data/leads.db` by default) -- leads,
per-request logs, checkpoints, and the cost ledger. No external infra
required; that's deliberate given the budget.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# fill in WEBSHARE_USERNAME / WEBSHARE_PASSWORD (see below) and TIER2_SEARCH_API_KEY
```

**Before running real traffic:** both providers' username-parameter syntax
for country targeting and sticky sessions (`src/proxy.py`) is implemented
against their publicly documented format as of this writing. Confirm it
still matches your dashboard first -- getting it wrong burns bandwidth for
nothing (paid, in DataImpulse's case). Same caution applies to the Google
Maps DOM selectors in `src/scraper.py`: Maps' markup changes over time, and
selectors are the most likely thing to need a touch-up (see the
maintenance note at the top of that file).

## Using Webshare (do this before spending on DataImpulse)

`PROXY_PROVIDER=webshare` in `.env` is the default. Webshare gives a
permanent free tier -- 10 proxies and 1GB of residential bandwidth per
month, no card required -- which is enough to run the pipeline against
real Google Maps traffic and shake out selector/config bugs at zero cost,
before spending the $5 DataImpulse credit on the real pilot.

1. **Sign up**: [webshare.io](https://www.webshare.io) -> free plan, no
   payment method needed.
2. **Get proxy credentials**: Dashboard -> Proxy -> Connection tab. Use the
   **Proxy Username / Proxy Password** shown there -- NOT your account
   login email/password, those are different credentials.
3. **Fill in `.env`**:
   ```
   PROXY_PROVIDER=webshare
   WEBSHARE_USERNAME=<proxy username from the dashboard>
   WEBSHARE_PASSWORD=<proxy password from the dashboard>
   ```
4. **Run a small test** to confirm the scraper actually extracts fields
   correctly before trusting it with paid bandwidth:
   ```bash
   python scripts/run_batch.py --city Lagos --categories clinic --pilot-only --max-leads 15
   python scripts/export_by_niche.py
   ```
   Open `output/master.csv` and manually check: are business names, phone
   numbers, and addresses populated and correct? If fields come back empty,
   that's the Google Maps selector drift mentioned above, not a proxy
   problem -- fix `src/scraper.py`'s `_extract_detail_fields` before
   spending real money on DataImpulse.
5. **Watch the free-tier ceiling**: since Webshare's tier is free rather
   than metered, `src/cost_tracker.py` tracks it as a hard *bandwidth* cap
   (`cost.webshare_free_tier_mb` in `config/settings.yaml`, default 950MB
   -- just under the real 1GB limit) rather than a dollar cap. It raises
   the same `CostCeilingExceeded` and pauses the run if you approach it.
6. **Switch to DataImpulse** once you're confident the scraper works:
   ```
   PROXY_PROVIDER=dataimpulse
   DATAIMPULSE_USERNAME=<from dataimpulse.com dashboard>
   DATAIMPULSE_PASSWORD=<from dataimpulse.com dashboard>
   ```
   then run `scripts/run_pilot.py` for the real, spec-scoped pilot.

Webshare's residential pool is smaller/lower-quality than DataImpulse's at
this tier, so don't be surprised if you see a higher CAPTCHA/error rate on
Webshare than on DataImpulse -- that's expected and is exactly why it's
positioned here as a free debugging step, not a permanent replacement for
the paid pilot.

## Running the pilot (do this first)

The spec requires a scoped pilot before any scaling: 200-500 raw leads, one
category, Lagos, 2-3 grid cells (`config/grid_lagos.yaml` zones flagged
`pilot: true`).

```bash
python scripts/run_pilot.py --category clinic
```

This prints a pass/fail report against every automatable pilot criterion
(raw lead count in range, error rate < 15%, bandwidth well under 1GB,
qualification pipeline producing a plausible pass/reject split), plus a
reminder for the two checks that require a human:

1. Spot-check 10-15 "qualified" leads by actually searching their names
   yourself to confirm they don't have a site.
2. Compare the pipeline's cost estimate against your real DataImpulse
   dashboard balance (`python scripts/check_cost.py`).

**Do not scale past a FAIL verdict.** Fix the underlying issue and re-run.

If the pilot is interrupted (Ctrl-C, host restart), it's resumable:

```bash
python scripts/run_pilot.py --resume-run-id <run_id printed at start>
```

Already-completed grid cells are skipped; scraping picks up where it left off.

## Running a general batch

```bash
python scripts/run_batch.py --city Lagos --categories clinic "law firm" "real estate agency" \
    --max-leads 2000
```

- Omit `--pilot-only` to run the full grid (all zones in `config/grid_<city>.yaml`).
- `--resume-run-id ID` continues an interrupted or cost-paused run.
- `--skip-scrape` re-runs qualification/dedup on already-scraped leads
  without hitting the proxy again (useful after tuning Tier 1/2 config).

## Checking the cost tracker

```bash
python scripts/check_cost.py
```

Prints cumulative proxy bandwidth/spend against the configured ceiling, and
Tier 2 search-API quota usage for the current month. Read-only, no cost to
run it.

### Cost guardrails

- Every scraped batch's bandwidth is recorded to `cost_ledger`
  (`src/cost_tracker.py`) immediately after the request, before the next
  one starts.
- `config/settings.yaml` -> `cost.global_ceiling_usd` (default **$4.50**,
  against the $5 pilot tier) is a **hard** ceiling: `CostTracker.record()`
  raises `CostCeilingExceeded` the instant cumulative spend crosses it, the
  pipeline cancels in-flight scrape tasks, checkpoints its progress, and
  marks the run `paused_cost_ceiling`. It will not silently keep going.
- A brand-new run refuses to start at all if a *previous* run already
  pushed cumulative spend past the ceiling -- the ceiling is account-wide,
  not per-run, because it's tracking real DataImpulse spend.
- Tier 2 (paid-adjacent, since it's rate-limited by a free quota) tracks
  usage per calendar month in `tier2_quota` and raises
  `Tier2QuotaExhausted` when the configured `free_quota_monthly` is hit;
  the pipeline catches this and marks remaining leads
  `pending_quota_exhausted` instead of crashing the run or silently
  skipping Tier 2 checks.
- Raise `global_ceiling_usd` deliberately in `config/settings.yaml` once
  you've topped up DataImpulse credit -- it will not creep upward on its own.

## Exporting leads

```bash
python scripts/export_by_niche.py --run-id <run_id>   # or omit --run-id for all runs
```

Writes `output/master.csv` plus one `output/<niche>.csv` per niche.
"Qualified" = Tier 1 pass, Tier 2 pass (or still pending because the free
quota ran out -- treated as an unverified candidate, not rejected), valid
Nigerian phone number, not flagged as a duplicate.

## Scaling safely

Per spec Section 4: don't jump straight to full scale. After a passing
pilot:

1. Add more `pilot: true`-equivalent zones to `config/grid_<city>.yaml`
   incrementally (or run without `--pilot-only`), re-checking
   `scripts/check_cost.py` and the error rate in `run_summary()` after each
   expansion.
2. Add categories one at a time in `config/categories.yaml` ->
   `pilot_categories`.
3. Only add a new city (Abuja, Port Harcourt) by creating a new
   `config/grid_<city>.yaml` after Lagos coverage is validated.
4. Raise `cost.global_ceiling_usd` only after confirming real DataImpulse
   spend matches the tracker's estimate -- see "Cost guardrails" above.

City-level proxy targeting (paid, beyond free country-level) is only worth
paying for if pilot data shows query-text filtering (e.g. "restaurants in
Ikeja, Lagos") isn't precise enough -- check this before spending on it.

## Grid cells

`src/grid.py` splits each zone's lat/lon bounding box into `cell_km`-wide
cells and issues one Maps search per cell per category, to get around the
~200-result cap per query. `config/grid_lagos.yaml` starts with smaller
cells (1km) in dense commercial zones (Victoria Island, Ikeja) and larger
cells (1.5-3km) in sparser zones (Lekki Phase 1, Surulere, Ikorodu) -- tune
`cell_km` per zone based on pilot results (too many empty-result cells
means cells are too small for that area; hitting the 200 cap on a cell
means it's too large).

## Tests

```bash
pytest tests/ -q
```

Covers the pure-function logic (grid generation, niche normalization,
phone validation, dedup, cost ceiling enforcement, Tier 1 qualification)
with no network or browser dependency. Stage A (Playwright scraping) and
Tier 2 (live search API) are not unit-tested here since they require a
live proxy/API credential and real Google Maps traffic -- validate those
end-to-end via the pilot run instead.

## Known limitations / stretch goals

- Google Maps DOM selectors (`src/scraper.py`) are the most likely
  maintenance point; Google changes markup periodically.
- CAC registration cross-check (Stage D stretch goal in the spec) is not
  implemented -- flagged as future work, not required for the pilot.
- Tier 2 only implements Serper.dev and Searlo; switching providers means
  adding a function to `_PROVIDERS` in `src/qualify_tier2.py`.
- Storage is single-file SQLite (no n8n Data Table / Supabase wiring,
  since neither was present in this repo). `scripts/export_by_niche.py`'s
  CSV output is the integration point if you want to load results into
  n8n or Postgres later.
