# Polymarket Flagger

A bot that watches Polymarket and sends you a Telegram alert when a sports bet looks underpriced.
It runs by itself every 15 minutes on GitHub's servers. There is nothing to keep running on your own computer.

This README is the single place to understand what the bot does today and how to change it.

---

## 1. What it does right now

Every 15 minutes it pulls the current sports markets from Polymarket, checks them against three rules ("flags"), and messages you on Telegram if a NEW market qualifies.

The three flags:

1. **UFC mispricing** - two fighters with similar career records, but the market prices one of them under 20%. (Uses real career records scraped from UFCStats.)
2. **UFC longshot** - any UFC fighter priced under 10%.
3. **Sports longshot** - any sports outcome priced under 10%, as long as the market has real money in it (a liquidity floor).

Sports currently scanned: **UFC/MMA only.**
Other sports (NBA, soccer, etc.) are intentionally turned off for now.
The flag logic still supports them, so re-adding a sport is a one-line change (see Section 4).

It only looks at real fight/match-outcome markets (who wins).
It ignores "prop" markets like "will X happen?" or over/under - that keeps the noise down.

Note: with UFC-only, a fighter under 10% trips both the UFC-longshot and sports-longshot rules, so an alert may show both tags for the same bet. That is expected and harmless.

You only get pinged when something NEW qualifies.
The same alert also lists markets that still qualify, with their updated percentages and a "(was X%)" so you can see movement.
Quiet cycles send nothing.

The message shows, per flagged bet: the sport, the market, the cheap side and its %, the volume and liquidity, which flags it hit, the fighter records (for mispricing), and a clickable Polymarket link.

---

## 2. How it runs (deployment)

- **Code lives at:** the private GitHub repo `theonlyrobocop123/polymarket-flagger`.
- **The engine:** a GitHub Actions workflow at `.github/workflows/flagger.yml` does one check per run.
- **The 15-minute timer:** a free cron-job.org job "pokes" GitHub every 15 minutes to start a run.
  We use an external poker because GitHub's own built-in schedule is unreliable for short intervals (it lagged to roughly every 2 hours).
  See `C:\dev\tools\cron-jobs.md` for the reusable recipe.
- **Secrets:** your Telegram bot token and chat id are stored as GitHub Actions secrets (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`), never in the code.
- **Memory:** the bot remembers what it already alerted on, plus the fighter records cache, on a separate git branch called `bot-state`. This keeps the main code history clean.

### To pause it
Disable the cron-job.org job (stops the 15-minute pokes), or in the GitHub repo go to Actions -> Polymarket Flagger -> "..." -> Disable workflow.
Re-enable the same way.

### To watch it
GitHub repo -> Actions tab shows every run, green (worked) or red (failed).

---

## 3. Where the code is (so you know what to change)

The code is small and each file has one job. All of it is under `polymarket_flagger/`.

| File | What it does |
|------|--------------|
| `config.py` | ALL the knobs: thresholds, which sports, cache age. Change settings here. |
| `models.py` | The data shapes (a Market, a FighterRecord, a flagged item). Rarely changed. |
| `polymarket_client.py` | Fetches markets from Polymarket and filters out prop markets. |
| `fighter_store.py` | Scrapes UFCStats fighter records (gets past their bot-check), caches them, matches names. |
| `flags.py` | The three flag rules. Change what qualifies here. |
| `state.py` | Remembers what was already alerted (NEW vs still-qualifying). |
| `telegram_notifier.py` | Builds the message text and sends it to Telegram. Change the message format here. |
| `main.py` | Ties it all together for one run. |
| `data/fighters_seed.json` | A backup list of ~4,500 fighters, used if a live scrape ever fails. |

The design write-up and the original build plan live in `docs/superpowers/` if you want the deeper reasoning.

---

## 4. How to make common changes

For each of these: edit the file, then commit and push (or just ask Claude to do it).
The live bot picks up the change on its next run.

**Change a threshold** (the %s, the record gap, the liquidity floor):
Edit `polymarket_flagger/config.py`. Every number is there with a clear name, for example:
- `flag2_ufc_threshold = 0.10` -> the UFC longshot cutoff (10%).
- `flag3_sports_threshold = 0.10` -> the sports longshot cutoff (10%).
- `flag3_min_liquidity = 5000.0` -> the "real money" floor.
- `flag1_underdog_max = 0.20` -> the mispricing underdog cutoff (20%).
- `flag1_gap_pct = 15.0` -> how close two fighters' records must be to count as "similar".

**Add or remove a sport:**
Edit the `sport_tag_slugs` list in `config.py`.
Use Polymarket's tag name (for example `"tennis"`, `"nba"`).

**Change what the alert looks like:**
Edit `telegram_notifier.py` (the `format_message` / `_render_item` functions).

**Change how often it runs:**
Edit the schedule on the cron-job.org job (not in the code).

**Change a flag's actual logic:**
Edit `flags.py`. Add tests in `tests/test_flags.py`.

---

## 5. Running and testing on your own computer

You normally never need to, but to try it locally:

```bash
pip install -r requirements.txt
cp .env.example .env        # then paste your Telegram token and chat id into .env
python -m polymarket_flagger.main
```

Run the tests (there are ~58, all should pass):

```bash
python -m pytest -q
```

Always run the tests before pushing a change.

---

## 6. Two things worth knowing (the tricky bits)

**Fighter records / UFCStats:**
UFCStats.com hides its data behind a browser check (a proof-of-work puzzle).
`fighter_store.py` solves that puzzle automatically to get the real data.
If that ever breaks, the bot falls back to the committed seed list (`data/fighters_seed.json`) and keeps working on slightly older records rather than dying.
The records refresh when the cache is older than `cache_max_age_days` (7 days).

**Never guessing a fighter:**
If a fighter's name is ambiguous (UFC has multiple "Bruno Silva") or can't be matched confidently, the bot skips the mispricing flag for that fight rather than risk using the wrong record.
The other two flags still work.

**No repeat spam:**
State only advances after a Telegram message actually sends.
So if a send ever fails, the NEW item is retried next run, never silently lost.

---

## 7. If you are picking this up cold

1. Read Section 1 (what it does) and Section 2 (how it runs).
2. To tweak behavior, Section 4 tells you the exact file.
3. The bot is already live and self-running - you do not need to "start" anything.
4. If something looks broken, check the GitHub Actions tab for a red run and open its log.
