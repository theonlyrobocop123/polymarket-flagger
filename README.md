# Polymarket Flagger

Polls Polymarket every 15 minutes and sends a Telegram alert when a sports outcome
trips one of three flags:

1. **UFC mispricing** - two fighters with similar career records, one priced under 20%.
2. **UFC longshot** - any UFC fighter priced under 15%.
3. **Sports longshot** - any sports outcome under 10%, above a liquidity floor.

Alerts fire only when a *new* market qualifies; still-qualifying markets are shown
with updated percentages for context.

## Setup

1. Create a Telegram bot with `@BotFather` (`/newbot`) and copy the token.
2. Message your new bot once, then get your numeric chat id from `@userinfobot`.
3. In the GitHub repo: Settings -> Secrets and variables -> Actions -> add:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. The workflow in `.github/workflows/flagger.yml` runs every 15 minutes automatically.
   Trigger a manual run from the Actions tab (`Run workflow`) to test.

## Local run

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your token and chat id
python -m polymarket_flagger.main
```

## Tests

```bash
python -m pytest -v
```

## Tuning

All thresholds live in `polymarket_flagger/config.py` (`Config`):
gap percentage, minimum fights, the three price thresholds, the liquidity floor,
and the name-match confidence threshold.

## How state works

The bot remembers what it already alerted on in `state.json`, committed to a
dedicated `bot-state` branch each run so `main` history stays clean. State only
advances after a Telegram message is successfully sent, so a new flag is never
silently dropped.
