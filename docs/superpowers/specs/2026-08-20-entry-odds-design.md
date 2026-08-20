# Entry Odds Advice - Design

Date: 2026-08-20.
Status: approved by Ricardo, ready for implementation.

## Purpose

Every Telegram alert gains one line that helps decide what odds to enter at.
It is an execution aid ("is now a good fill given recent trading"), not extra evidence that the bet itself is good.
The existing flags remain the only value filter.

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
- 24h net change, 24h low, 7d range: from the hourly midpoint series.
- Trend: EMA-8 vs EMA-21 on hourly closes.
  - Rising: EMA-8 > EMA-21 and 24h change >= +1pt.
  - Falling: EMA-8 < EMA-21 and 24h change <= -1pt.
  - Flat: everything else.

## Recommendation rule

- Rising: enter now at market (the edge is eroding; the flag already confirmed the price qualifies).
- Flat: enter now if current <= 24h VWAP, otherwise rest a limit at the 24h VWAP.
- Falling: rest a limit at the 24h low, so a fill only happens into continued weakness.

## Message format

One line per alert item, shown on new, still-qualifying, and preview items:

```
📈 now 12% · VWAP 13.5% (24h) / 14.2% (7d) · 7d range 9-16% · trend ↓ → limit @ 11%
```

Trend arrows: ↑ rising, ↔ flat, ↓ falling.
Suggestions render as "enter now" or "limit @ X%".

## Failure handling (fail open)

The alert still goes out without the entry line when:

- either endpoint fails or times out,
- fewer than 5 trades exist in the last 24h,
- the hourly series is too short for the EMAs.

Trade pagination is capped (500 per page, at most 8 pages) so a runaway market cannot stall the cycle.

## Non-goals

- No fair-value model of the odds; the line never claims the bet is mispriced.
- No storage of odds history in bot state.
- No change to flag thresholds or dedupe behavior.
