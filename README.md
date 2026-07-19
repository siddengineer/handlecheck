# HandleCheck

A username availability scanner. Type a handle, hit **Scan**, and it pings
~27 platforms (dev, social, creative, writing, gaming, and a few domains)
to tell you which ones the exact string is free on.

- **Backend:** Python + FastAPI (`backend/`)
- **Frontend:** plain HTML/CSS/JS (`frontend/`) — served *by* the backend, so
  starting the backend starts the whole app. No separate frontend server needed.

## How it works

For each platform, HandleCheck requests the platform's public profile URL
(or a small public API) and reads the response:

- `404` → **available**
- `200` (with a real profile) → **taken**
- Anything ambiguous, blocked, or erroring → **unknown**

Domains (`.com`, `.io`, `.dev`, `.app`) are checked via DNS resolution instead
of HTTP, as a "does this resolve" heuristic.

A few platforms (X/Twitter, Instagram) actively block automated lookups or
require a JS-rendered page to load — those are always reported as
**unknown** with a note, rather than guessing.

No personal data is collected or stored. Each scan just makes outbound
requests to public profile URLs for the exact string you typed.

## Run it

Requires Python 3.9+.

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open **http://127.0.0.1:8000** in your browser. That's it — the
FastAPI app serves the frontend directly, so there's nothing else to start.

## Project structure

```
handlecheck/
├── backend/
│   ├── main.py          # FastAPI app, /api routes, serves the frontend
│   ├── platforms.py     # the list of platforms + how each is checked
│   └── requirements.txt
└── frontend/
    ├── index.html
    ├── style.css
    └── app.js
```

## Customizing

- Add/remove platforms by editing the `PLATFORMS` list in `backend/platforms.py`.
  Most platforms just need a URL template and use the generic `status_from_code`
  checker (404 = available, 200 = taken). A few (Reddit, Keybase, Steam,
  Telegram, Hacker News, Docker Hub, itch.io, domains) have small custom
  checkers because their availability signal isn't a plain status code.
- Concurrency and per-request timeout are set at the top of `main.py`
  (`CONCURRENCY_LIMIT`) and `platforms.py` (`TIMEOUT`).

## Notes & limitations

- This is a best-effort scanner, not a guarantee. Sites change their pages,
  add bot protection, or rate-limit — treat "unknown" as "go check by hand"
  and treat everything as a snapshot at scan time, not a legal guarantee
  the name is yours to take.
- Some platforms may occasionally rate-limit or block the server's IP if you
  run a lot of scans back-to-back.
