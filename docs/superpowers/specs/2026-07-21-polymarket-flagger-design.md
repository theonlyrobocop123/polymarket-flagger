# Polymarket Flagger - Design

Date: 2026-07-21
Status: Approved, ready for implementation planning

## Purpose

Monitor Polymarket for underpriced sports outcomes and alert the user on Telegram.
The bot polls Polymarket every 15 minutes, evaluates three flags, and sends a Telegram message only when a new qualifying market appears.
It tracks state so the same market is not re-alerted every cycle, and it shows updated percentages for markets that still qualify.

## The three flags

A single market is evaluated against all three flags.
One alert is sent per market, tagged with every flag it hits (deduped).

| # | Name | Condition | Data needed |
|---|------|-----------|-------------|
| 1 | UFC mispricing | Both fighters' career win% are within 15 percentage points of each other, AND the market prices one fighter below 20% | Polymarket price + UFCStats career records |
| 2 | UFC longshot | Any UFC fighter priced below 15% | Polymarket price only |
| 3 | Sports longshot | Any sports outcome priced below 10%, above a liquidity floor | Polymarket price only |

### Flag parameters (tunable defaults)

- Flag 1 "similar records" gap: 15 percentage points of career win%.
- Flag 1 minimum fights: each fighter must have at least 4 career fights for the record comparison to count. If either fighter cannot be confidently matched to UFCStats, Flag 1 is skipped for that market (logged), but Flags 2 and 3 still apply.
- Flag 3 liquidity floor: minimum market liquidity (default to be set during build, e.g. $5,000) so dead markets are excluded.

These live in a single config block so they can be tuned without code changes.

## Data sources

Both are free and require no API key.

### Polymarket Gamma API

- Base URL: `https://gamma-api.polymarket.com`
- No authentication for read endpoints.
- Sports markets: filter by sport tags.
- UFC markets: filter events by `tag_slug=ufc` on `/events`, then read the moneyline market within each event.
- Per-market fields used: `question` (title), `outcomes` (stringified JSON array of outcome names), `outcomePrices` (stringified JSON array of prices in same order), `volumeNum`, `liquidityNum`, `endDate`, `slug`, `active`, `closed`.
- Quirk: `outcomes`, `outcomePrices`, and `clobTokenIds` are JSON-encoded strings and must be parsed client-side.
- A UFC moneyline market has exactly two outcomes equal to the two fighter names (not "Yes"/"No"), which distinguishes it from prop markets on the same card.
- Rate limits are far above what a 15-minute poll needs, so no rate-limit engineering is required.

### UFCStats.com (career records)

- Full fighter roster is listed A to Z at `ufcstats.com/statistics/fighters?char={a..z}&page=all`, with W-L-D columns and nicknames.
- No official anti-bot ToS clause found; widely scraped by the MMA data community.
- Strategy: scrape the full roster once, cache it locally, refresh weekly.
- Update latency reflects each fighter's record as of their last completed fight, which is correct going into an upcoming bout.

### Name matching

Polymarket fighter names may differ from UFCStats (nicknames, accents, suffixes like "Jr").

- Normalize both sides with `unidecode` (strip accents) and lowercase.
- Match with `rapidfuzz` `token_sort_ratio` against both full name and nickname.
- Accept the best match above a confidence threshold (default 85).
- Below threshold, fail loudly: skip Flag 1 for that market and log it for manual review. Never guess a record.

## Architecture

A single Python service, one run per cycle, triggered every 15 minutes by GitHub Actions cron.

Components, each with one clear responsibility:

1. **Polymarket client** - fetch active sports and UFC markets, parse the stringified fields, return normalized market objects (title, outcomes, prices, volume, liquidity, slug, sport, is_ufc).
2. **Fighter record store** - scrape and cache the UFCStats roster; look up a career record by name via fuzzy matching; expose a refresh function.
3. **Flag evaluator** - given normalized markets and the record store, apply the three flags and return qualifying items (market + flagged outcome + price + flags hit + supporting record data).
4. **State store** - a JSON file holding the previously-qualifying set (keyed by market id plus flagged outcome). Diffs current vs previous to classify each item as NEW or STILL QUALIFYING, and records the previous price for the "was X%" display.
5. **Telegram notifier** - format the message and send it via the Telegram Bot API. Only sends when at least one NEW item exists.
6. **Orchestrator** - the entry point that wires the above together for one cycle.

## State and dedupe

- State key: `market_id + flagged_outcome`.
- Each cycle computes the current qualifying set.
  - NEW: in current, not in previous.
  - STILL QUALIFYING: in both. Previous price is carried for the "was X%" display.
  - Items that dropped out are simply removed from state (no "no longer qualifying" alert).
- A message is sent only when there is at least one NEW item. The STILL QUALIFYING section is included for context in that same message.
- On GitHub Actions, the state JSON is persisted by committing it to a dedicated `bot-state` branch each run, isolated from `main`.

## Message format

Telegram message, HTML or Markdown parse mode, links clickable.
Sent only when there is at least one NEW item.

```
🚩 Polymarket Flags · 2026-07-21 14:15 UTC

🆕 NEW (2)

🥊 Mike Davis vs. Nurullo Aliev
Aliev @ 8% · vol $18k · liq $18k
Flags: UFC longshot <15% · Sports longshot <10%
🔗 Open on Polymarket  (link to polymarket.com/event/<slug>)

🥊 Jones vs. Miocic
Miocic @ 17% · vol $220k · liq $95k
Flags: UFC mispricing - Jones 27-1 (96%) vs Miocic 20-4 (83%), 13-pt gap
🔗 Open on Polymarket

🔁 STILL QUALIFYING (1)

⚽ Team X vs. Team Y - Draw
Draw @ 6% (was 8%) · vol $60k · liq $30k
Flags: Sports longshot <10%
🔗 Open on Polymarket
```

Each line item shows:

- Sport emoji plus market title.
- The flagged outcome and its price percent (the specific cheap side).
- Volume and liquidity, so tradeability is visible.
- Which flags it hit, as tags.
- For Flag 1 (mispricing): both fighters' career records, win percentages, and the gap.
- A clickable Polymarket link, built from the market or event slug (`https://polymarket.com/event/<slug>`).
- STILL QUALIFYING items add "(was X%)" to show the move.

## Configuration and secrets

- Telegram bot token and chat id: provided by the user, stored as GitHub Actions secrets, never committed.
- All flag thresholds and the liquidity floor live in one config block.

## Hosting and scheduling

- GitHub Actions scheduled workflow, cron every 15 minutes.
- The workflow checks out the repo, installs dependencies, runs one cycle, and commits updated state to the `bot-state` branch.
- Note: GitHub Actions cron can drift by a few minutes under load. Acceptable for this use case.

## Error handling

- Polymarket API failure: log and exit the cycle cleanly; try again next cycle. Do not crash the workflow in a way that loses state.
- UFCStats scrape failure or stale cache: fall back to the last good cache; if a fighter is missing, skip Flag 1 for that market only.
- Name match below confidence: skip Flag 1 for that market, log for review.
- Telegram send failure: log; state is still saved so the item is not lost, but note it may then be treated as already-seen. Mitigation: only advance state after a successful send.

## Testing

- Unit test each flag's condition logic with synthetic market and record inputs, including boundary cases (exactly 15%, exactly the gap, missing fighter).
- Unit test name matching with accented names, nicknames, and suffixes.
- Unit test the NEW vs STILL QUALIFYING diff logic.
- Unit test the message formatter against a fixed input to lock the layout.
- Integration test the Polymarket client against a recorded API response fixture.

## Out of scope (for now)

- Automated trading or order placement.
- Non-sports markets.
- Historical backtesting of flag profitability.
- A "no longer qualifying" notification.
