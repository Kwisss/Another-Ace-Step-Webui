import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

DB_PATH = Path("data/acestep.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT UNIQUE NOT NULL,
    title TEXT,
    prompt TEXT,
    lyrics TEXT,
    bpm INTEGER,
    key_scale TEXT,
    time_signature TEXT,
    duration REAL,
    vocal_language TEXT DEFAULT 'auto',
    batch_size INTEGER DEFAULT 2,
    inference_steps INTEGER DEFAULT 50,
    guidance_scale FLOAT,
    shift FLOAT DEFAULT 3.0,
    input_seed TEXT DEFAULT '-1',
    audio_format TEXT DEFAULT 'mp3',
    thinking INTEGER DEFAULT 1,
    use_cot_caption INTEGER DEFAULT 0,
    use_cot_language INTEGER DEFAULT 0,
    lm_temperature FLOAT DEFAULT 0.85,
    lm_cfg_scale FLOAT DEFAULT 2.5,
    lm_top_k INTEGER DEFAULT 0,
    lm_top_p FLOAT DEFAULT 0.9,
    lm_repetition_penalty FLOAT DEFAULT 1.0,
    seed_value TEXT,
    audio_path TEXT,
    liked INTEGER DEFAULT 0,
    listens INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending',
    cover_art TEXT DEFAULT 'algorithmic',
    image_path TEXT
);

CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (playlist_id, track_id),
    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);
"""


class Database:
    def __init__(self):
        DB_PATH.parent.mkdir(exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # ── Tracks ──────────────────────────────────────────────

    def create_track(
        self, task_id: str, prompt: str, lyrics: str = "", title: Optional[str] = None, vocal_language: str = "auto", batch_size: int = 2, inference_steps: int = 50, guidance_scale: float = None, shift: float = 3.0, input_seed: str = "-1", audio_format: str = "mp3", thinking: bool = True, use_cot_caption: bool = False, use_cot_language: bool = False, lm_temperature: float = 0.85, lm_cfg_scale: float = 2.5, lm_top_k: int = 0, lm_top_p: float = 0.9, lm_repetition_penalty: float = 1.0, cover_art: str = "algorithmic"
    ) -> int:
        if title is None:
            title = self._make_title(prompt)
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO tracks (task_id, title, prompt, lyrics, vocal_language, batch_size, inference_steps, guidance_scale, shift, input_seed, audio_format, thinking, use_cot_caption, use_cot_language, lm_temperature, lm_cfg_scale, lm_top_k, lm_top_p, lm_repetition_penalty, cover_art) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_id, title, prompt, lyrics, vocal_language, batch_size, inference_steps, guidance_scale, shift, input_seed, audio_format, int(thinking), int(use_cot_caption), int(use_cot_language), lm_temperature, lm_cfg_scale, lm_top_k, lm_top_p, lm_repetition_penalty, cover_art),
            )
            return cur.lastrowid

    def complete_track(
        self,
        task_id: str,
        local_filename: str,
        prompt: str,
        lyrics: str,
        bpm: Optional[int] = None,
        key_scale: Optional[str] = None,
        time_signature: Optional[str] = None,
        duration: Optional[float] = None,
        seed_value: str = "",
        image_path: Optional[str] = None,
    ):
        with self._conn() as conn:
            conn.execute(
                """UPDATE tracks
                   SET status='complete', audio_path=?, prompt=?, lyrics=?, bpm=?, key_scale=?, time_signature=?, duration=?, seed_value=?, image_path=?
                   WHERE task_id=?""",
                (local_filename, prompt, lyrics, bpm, key_scale, time_signature, duration, seed_value, image_path, task_id),
            )

    def fail_track(self, task_id: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE tracks SET status='failed' WHERE task_id=?", (task_id,)
            )

    def get_track(self, track_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tracks WHERE id=?", (track_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_track_by_task(self, task_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tracks WHERE task_id=?", (task_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_library(
        self,
        search: Optional[str] = None,
        liked_only: bool = False,
        sort_by: str = "created_at",
        order: str = "DESC",
        limit: int = 100,
        offset: int = 0,
    ) -> list:
        # Changed: Include pending and processing, hide failed
        conditions = ["status != 'failed'"]
        params: list = []
        if search:
            conditions.append("(title LIKE ? OR prompt LIKE ? OR lyrics LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        if liked_only:
            conditions.append("liked=1")
            
        where = "WHERE " + " AND ".join(conditions)
        
        valid_sorts = {"title", "bpm", "key_scale", "duration", "created_at", "listens"}
        sort_col = sort_by if sort_by in valid_sorts else "created_at"
        sort_dir = "ASC" if order.upper() == "ASC" else "DESC"

        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM tracks {where} ORDER BY {sort_col} {sort_dir} LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            return [dict(r) for r in rows]

    def count_library(
        self,
        search: Optional[str] = None,
        liked_only: bool = False,
    ) -> int:
        conditions = ["status != 'failed'"]
        params: list = []
        if search:
            conditions.append("(title LIKE ? OR prompt LIKE ? OR lyrics LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        if liked_only:
            conditions.append("liked=1")
        where = "WHERE " + " AND ".join(conditions)
        with self._conn() as conn:
            row = conn.execute(f"SELECT COUNT(*) FROM tracks {where}", params).fetchone()
            return row[0] if row else 0

    def increment_listens(self, task_id: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE tracks SET listens = listens + 1 WHERE task_id = ?",
                (task_id,)
            )

    def get_neighbors(
        self, 
        task_id: str, 
        playlist_id: Optional[int] = None, 
        search: str = "", 
        liked_only: bool = False, 
        sort_by: str = "created_at", 
        order: str = "DESC"
    ) -> tuple[Optional[str], Optional[str]]:
        """Finds the Previous and Next task_ids based on the current context."""
        with self._conn() as conn:
            if playlist_id:
                rows = conn.execute("""
                    SELECT t.task_id FROM tracks t
                    JOIN playlist_tracks pt ON t.id = pt.track_id
                    WHERE pt.playlist_id=? AND t.status='complete'
                    ORDER BY pt.added_at DESC
                """, (playlist_id,)).fetchall()
            else:
                conditions = ["status='complete'"]
                params = []
                if search:
                    conditions.append("(title LIKE ? OR prompt LIKE ? OR lyrics LIKE ?)")
                    params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
                if liked_only:
                    conditions.append("liked=1")
                    
                where = "WHERE " + " AND ".join(conditions)
                valid_sorts = {"title", "bpm", "key_scale", "duration", "created_at", "listens"}
                sort_col = sort_by if sort_by in valid_sorts else "created_at"
                sort_dir = "ASC" if order.upper() == "ASC" else "DESC"

                rows = conn.execute(f"""
                    SELECT task_id FROM tracks {where} ORDER BY {sort_col} {sort_dir}
                """, params).fetchall()

            ids = [r["task_id"] for r in rows]
            try:
                idx = ids.index(task_id)
                prev_id = ids[idx - 1] if idx > 0 else None
                next_id = ids[idx + 1] if idx < len(ids) - 1 else None
                return prev_id, next_id
            except ValueError:
                return None, None

    def get_max_version(self, base_title: str, exclude_task_id: str) -> int:
        """Returns the highest ' vN' suffix found for base_title (excluding the task itself).
        Returns 0 if no versioned titles exist. main.py handles the has_base check separately."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT MAX(CAST(SUBSTR(title, INSTR(title, ' v') + 2) AS INTEGER))
                   FROM tracks WHERE title LIKE ? || ' v%' AND task_id != ?""",
                (base_title, exclude_task_id),
            ).fetchone()
            return row[0] or 0

    def toggle_like(self, track_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT liked FROM tracks WHERE id=?", (track_id,)
            ).fetchone()
            if not row:
                return False
            new_val = 0 if row["liked"] else 1
            conn.execute(
                "UPDATE tracks SET liked=? WHERE id=?", (new_val, track_id)
            )
            return bool(new_val)

    def delete_track(self, track_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM tracks WHERE id=?", (track_id,))

    # ── Playlists ────────────────────────────────────────────

    def create_playlist(self, name: str, description: str = "") -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO playlists (name, description) VALUES (?, ?)",
                (name, description),
            )
            return cur.lastrowid

    def get_playlists(self) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT p.*, COUNT(pt.track_id) as track_count
                   FROM playlists p
                   LEFT JOIN playlist_tracks pt ON p.id = pt.playlist_id
                   GROUP BY p.id
                   ORDER BY p.created_at DESC"""
            ).fetchall()
            return [dict(r) for r in rows]

    def get_playlist(self, playlist_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM playlists WHERE id=?", (playlist_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_playlist_tracks(self, playlist_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT t.* FROM tracks t
                   JOIN playlist_tracks pt ON t.id = pt.track_id
                   WHERE pt.playlist_id=? AND t.status='complete'
                   ORDER BY pt.added_at DESC""",
                (playlist_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def add_to_playlist(self, playlist_id: int, track_id: int):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id) VALUES (?,?)",
                (playlist_id, track_id),
            )

    def remove_from_playlist(self, playlist_id: int, track_id: int):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM playlist_tracks WHERE playlist_id=? AND track_id=?",
                (playlist_id, track_id),
            )

    def delete_playlist(self, playlist_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))

    def get_track_playlist_ids(self, track_id: int) -> list[int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT playlist_id FROM playlist_tracks WHERE track_id=?", (track_id,)
            ).fetchall()
            return [r["playlist_id"] for r in rows]

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _make_title(prompt: str) -> str:
        words = prompt.strip().split()[:6]
        title = " ".join(words)
        return title.capitalize() if title else "Untitled"