# Entry Odds Context - Design

Date: 2026-08-20.
Status: implemented.
Revised 2026-08-21 per Ricardo: the trend classification and entry recommendation were removed.
The line is now pure factual context; Ricardo makes the entry decision himself.

## Purpose

Every Telegram alert gains one line of execution context: the current price against recent volume-weighted trading and the recent range.
It is an execution aid ("is now a good fill given recent trading"), not extra evidence that the bet itself is good.
The existing flags remain the only value filter.
It applies to every flagged item regardless of which flag fired.

## Data sources

Both are free public endpoints, fetched at alert time only for items actually being sent.
No local history storage is needed.

1. Trade history: `https://data-api.polymarket.com/trades?market=<conditionId>` (paginated, trade-level price/size/timestamp/outcome).
2. Price history: `https://clob.polymarket.com/prices-history?market=<clobTokenId>&interval=1w&fidelity=60` (hourly midpoints, 1 week).

To support this, `Market` and `QualifyingItem` carry `condition_id` and the flagged outcome's `clob_token_id` (parsed from Gamma's `conditionId` and `clobTokenIds`, which align with `outcomes` order).

## Computation (per flagged outcome)

Trades are normalized to the flagged outcome.
In a binary market both tokens are the same economic instrument, so a trade on the other outcome at price p counts as a flagged-outcome trade at 1 - p.

- 24h VWAP and 7d VWAP: sum(price x size) / sum(size) over trades in the window.
- 7d range: min and max of the hourly midpoint series.

## Message format

One line per alert item, shown on new, still-qualifying, and preview items:

```
📈 now 12% · VWAP 13.5% (24h) / 14.2% (7d) · 7d range 9-16%
```

## Degradation (per component, fail soft)

UFC prelim markets trade thinly, so each component degrades independently instead of gating the whole line:

- A VWAP with no trades in its window renders as "n/a".
- The 7d range is omitted when the price history has fewer than 2 points.
- The whole line is omitted only when there are no trades and no history at all, or an endpoint fails.
- A failure never blocks or delays the alert itself.

Trade pagination is capped (500 per page, at most 8 pages) so a runaway market cannot stall the cycle.

## Non-goals

- No entry recommendation, trend call, or suggested limit price (removed in the 2026-08-21 revision).
- No fair-value model of the odds; the line never claims the bet is mispriced.
- No storage of odds history in bot state.
- No change to flag thresholds or dedupe behavior.
