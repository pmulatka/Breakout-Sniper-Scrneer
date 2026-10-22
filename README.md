# Breakout Sniper Screener — Angel One relay test

Prepared by Pramod Mulatkar · 22 Oct 2026, 14:05 IST · Test build v0.1

This is a **technical test only**. It proves that Angel One login, history download,
batch quotes and browser storage work through a stateless relay, before any screener
screens are built. It is **separate from the live Breakout Sniper** — new repo, new
Railway service. It never places orders and stores nothing on the server.

## Files

| File | What it is |
| --- | --- |
| `app.py` | Flask relay: forwards your own Angel One calls, serves the test page |
| `static/test.html` | The test page (buttons + results + log) |
| `requirements.txt` | Python packages |
| `Procfile` | Start command for Railway |

## Deploy (after market hours)

1. On GitHub, create a **new private repo** named `sniper-screener`.
2. Upload all files with **Add file → Upload files** (keep the `static` folder:
   drag the whole folder in).
3. On Railway, in your existing project or a new one: **New → GitHub Repo →
   sniper-screener**. This creates a separate service; the live Sniper is untouched.
4. In the new service's **Variables**, add `RELAY_ACCESS_KEY` = any long password you
   choose. (Optional but recommended — it stops strangers using the relay.)
5. **Settings → Networking → Generate Domain.** Open the URL; `/health` should show
   `"orders": "none"`.

## Run the test

1. Open the Railway URL. Enter the relay key, your SmartAPI API key, client code,
   PIN and a fresh TOTP. Click **Log in**.
2. Click **Load instrument list**.
3. **History backfill test:** start with **50 stocks**. If clean, run again with **500**.
4. **Daily top-up test:** run with **500 stocks**.
5. **Check storage.**
6. Click **Copy results + log** and paste it into the chat.
7. **Log out**, then **Delete test data** if you want.

Repeat once on your **phone browser** (steps 1–5 with 50 stocks) and paste those
results too.

## What the results will tell us

- Whether login through the relay is accepted by Angel One.
- The real sustained download rate and whether rate limits trigger.
- How long a full first-time backfill would take, and how much browser space it needs.
- Whether the batch quote call returns open/high/low/close **and volume** for the
  daily top-up.
- Whether the browser grants persistent storage (so data isn't wiped).
