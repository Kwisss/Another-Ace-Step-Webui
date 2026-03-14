# ACE-Step UI — Python/FastAPI Edition

A clean, local music generation UI built with **FastAPI + Jinja2 + HTMX + plain CSS**.

## Stack

| Layer     | Tech                                      |
|-----------|-------------------------------------------|
| Backend   | FastAPI + Uvicorn                         |
| Templates | Jinja2                                    |
| Frontend  | HTMX 1.9 (native SSE)                    |
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
- **Remix** — use audio codes or reference audio to remix existing tracks
- **LoRA Management** — load and configure custom LoRA adapters
- **Htmx Polling** — status via simple htmx polling for song/remix/inpaint generation, audio codes extraction, metadata extraction, and cover art updates
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
│   └── acestep.db
├── static/
│   ├── style.css        # CSS styles
│   ├── audio/           # Generated audio files
│   └── covers/          # Generated cover art
└── templates/
    ├── base.html        # Base template with header/footer
    ├── index.html       # Main generation page
    ├── library.html     # Library/track listing page
    ├── playlists.html   # Playlists overview
    ├── playlist_detail.html
    ├── remix.html       # Remix page with audio codes
    ├── lora.html        # LoRA management page
    ├── track_detail.html
    └── partials/
        ├── form_engine_settings.html
        ├── form_llm_settings.html
        ├── form_musical_metadata.html
        ├── form_shared_script.html
        ├── mini_library.html
        ├── player_bar.html
        ├── progress_card.html
        ├── progress_row.html
        ├── track_card.html
        └── track_row.html
```

## Pages

| Page | Description |
|------|-------------|
| `/` | Main generation page with all generation settings |
| `/remix` | Remix page for using audio codes/reference audio |
| `/library` | Browse, search, filter library |
| `/playlists` | Create and manage playlists |
| `/playlists/{id}` | View playlist contents |
| `/lora` | Load and manage LoRA adapters |
| `/track/{id}` | View detailed information about a specific track |

## HTMX Partials

| Partial | Purpose |
|---------|---------|
| `player_bar.html` | Persistent bottom audio player |
| `track_card.html` | Visual card representation of a track |
| `track_row.html` | Table row representation of a track |
| `progress_card.html` | Loading state card during generation |
| `progress_row.html` | Loading state table row |
| `mini_library.html` | Mini library view with recent tracks |
| `form_*` | Shared form configuration sections |
