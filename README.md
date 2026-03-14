# ACE-Step UI — Python/FastAPI Edition

A clean, local music generation UI built with **FastAPI + Jinja2 + HTMX + plain CSS**.

## Stack

| Layer     | Tech                                      |
|-----------|-------------------------------------------|
| Backend   | FastAPI + Uvicorn                         |
| Templates | Jinja2                                    |
| Frontend  | HTMX 1.9 + HTMX SSE extension            |
| Styles    | Plain CSS (no framework)                  |
| Database  | SQLite (via stdlib `sqlite3`)             |
| AI Engine | ACE-Step 1.5 REST API on port 8001        |

## Setup

```bash
# 1. Install Python deps
pip install -r requirements.txt

# 2. Make sure ACE-Step is running on port 8001
#    (in your ACE-Step-1.5 directory)
uv run acestep-api --port 8001

# 3. Start this UI
uvicorn main:app --reload --port 3000
```

Open http://localhost:3000

## Features

- **Generate** — prompt, lyrics, duration, BPM, thinking mode, seed, inference steps
- **SSE progress** — live status via Server-Sent Events (no polling loop on the client)
- **Library** — browse, search, filter by liked, play in bottom bar
- **Likes** — toggle ♥ on any track (HTMX in-place swap)
- **Playlists** — create, manage, add/remove tracks
- **Bottom player** — persistent audio bar, loads any track without page reload
- **Audio proxy** — `/audio/{task_id}` streams audio from ACE-Step API

## Configuration

Edit `ace_client.py` to change the ACE-Step API base URL (default: `http://localhost:8001`).

## Project Structure

```
ace_step_ui/
├── main.py              # FastAPI routes
├── db.py                # SQLite helpers
├── ace_client.py        # ACE-Step HTTP client
├── requirements.txt
├── data/                # SQLite DB (auto-created)
├── static/
│   └── style.css
└── templates/
    ├── base.html
    ├── index.html
    ├── library.html
    ├── playlists.html
    ├── playlist_detail.html
    └── partials/
        ├── progress_card.html
        ├── track_card.html
        └── player_bar.html
```
