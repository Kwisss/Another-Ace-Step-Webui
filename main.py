from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json
import httpx
from contextlib import asynccontextmanager
from typing import Optional
import urllib.parse
from pathlib import Path
import os.path as osp
import uuid
import hashlib
from PIL import Image, ImageDraw, ImageFilter
import random
import math
import asyncio
from datetime import datetime, timezone
from db import Database
from ace_client import AceStepClient

# ── App setup ────────────────────────────────────────────────

AUDIO_DIR = Path("static/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
COVER_DIR = Path("static/covers")
COVER_DIR.mkdir(parents=True, exist_ok=True)

def neon_line(base_img, points, color):
    width, height = base_img.size
    for w, blur in [(16, 12), (8, 6), (3, 0)]:
        temp = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        td = ImageDraw.Draw(temp)
        td.line(points, fill=color + (255,), width=w)
        if blur > 0:
            temp = temp.filter(ImageFilter.GaussianBlur(blur))
        base_img.alpha_composite(temp)

def triangle_wave(x):
    return 2 * abs(2 * (x % 1) - 1) - 1

def square_wave(x):
    return 1 if math.sin(x * 2 * math.pi) >= 0 else -1

def generate_memorable_neon(seed=42, width=400, height=400):
    random.seed(seed)
    base = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    neon_colors = [(255, 50, 190), (50, 255, 50), (50, 100, 255), (255, 200, 50), (0, 255, 255), (255, 80, 80), (180, 80, 255)]
    cx, cy = width // 2, height // 2
    orientation = random.choice(["horizontal", "vertical", "diag_up", "diag_down"])
    waveform = random.choice(["sine", "triangle", "square"])

    def wave_func(t):
        if waveform == "sine": return math.sin(t)
        elif waveform == "triangle": return triangle_wave(t / (2 * math.pi))
        else: return square_wave(t / (2 * math.pi))

    amplitude = random.randint(30, 80)
    freq = random.uniform(0.01, 0.04)
    phase = random.uniform(0, math.pi * 2)
    spacing = random.randint(20, 40)

    for i in range(6):
        color = random.choice(neon_colors)
        offset = (i - 3) * spacing
        points = []
        for t in range(0, width, 5):
            val = wave_func(t * freq + phase) * amplitude
            if orientation == "horizontal": x, y = t, int(cy + offset + val)
            elif orientation == "vertical": x, y = int(cx + offset + val), t
            elif orientation == "diag_up": x, y = t, int((t * 0.5) + offset + val)
            else: x, y = t, int((height - t * 0.5) + offset + val)

            if 0 <= x < width and 0 <= y < height: points.append((x, y))
            else:
                if len(points) > 1: neon_line(base, points, color)
                points = []
        if len(points) > 1: neon_line(base, points, color)

    arc_palette = random.sample(neon_colors, 2)
    for _ in range(8):
        color = random.choice(arc_palette)
        radius = random.randint(50, 180)
        start, end = random.randint(0, 360), random.randint(0, 360) + random.randint(40, 120)
        bbox = [(cx - radius, cy - radius), (cx + radius, cy + radius)]
        for w, blur in [(10, 8), (4, 3), (2, 0)]:
            temp = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            td = ImageDraw.Draw(temp)
            td.arc(bbox, start=start, end=end, fill=color + (255,), width=w)
            if blur > 0: temp = temp.filter(ImageFilter.GaussianBlur(blur))
            base.alpha_composite(temp)
            
    return Image.alpha_composite(Image.new("RGBA", (width, height), (0, 0, 0, 255)), base).convert("RGB")

async def generate_cover_art(task_id: str, style: str) -> str:
    if style == "none" or not style: return ""
    filename = f"{task_id}.png"
    dest = COVER_DIR / filename
    if dest.exists(): return filename
    
    try:
        if style == "picsum":
            url = f"https://picsum.photos/seed/{task_id}/400/400"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, follow_redirects=True, timeout=10.0)
                if resp.status_code == 200:
                    dest.write_bytes(resp.content)
                    return filename
        elif style == "algorithmic":
            seed_val = int(hashlib.md5(task_id.encode()).hexdigest(), 16) % (2**32)
            def _gen():
                img = generate_memorable_neon(seed=seed_val, width=400, height=400)
                img.save(dest)
            await asyncio.to_thread(_gen)
            return filename
    except Exception as e:
        print(f"Cover art generation failed: {e}")
    return ""


async def _update_cover_art(task_id: str, style: str) -> None:
    """Fire-and-forget: generate cover art after the track is already saved to DB.
    
    Called via asyncio.create_task() from poll_status so the heavy PIL/HTTP work
    doesn't block the status response. The track card will initially render without
    a cover; it appears on the next page load or navigation.
    """
    try:
        image_path = await generate_cover_art(task_id, style)
        if image_path:
            with db._conn() as conn:
                conn.execute(
                    "UPDATE tracks SET image_path=? WHERE task_id=?",
                    (image_path, task_id)
                )
    except Exception as e:
        print(f"Background cover art update failed for {task_id}: {e}")
    
db = Database()
ace = AceStepClient()

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await ace.close()

app = FastAPI(lifespan=lifespan, title="ACE-Step UI")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── Template filters ─────────────────────────────────────────

def fmt_duration(seconds) -> str:
    # Safely handle ANY weird string/value the API or DB returns to prevent lockups
    if seconds in (None, "", "null", "None", "auto"):
        return "--:--"
    try:
        m, s = divmod(int(float(seconds)), 60)
        return f"{m}:{s:02d}"
    except Exception:
        return "--:--"

def fmt_date(ts: str) -> str:
    if not ts:
        return ""
    return str(ts)[:10]

templates.env.filters["duration"] = fmt_duration
templates.env.filters["date"] = fmt_date

# ── Helpers ──────────────────────────────────────────────────
def safe_int(val):
    try: return int(float(val))
    except (ValueError, TypeError): return None

def safe_float(val):
    try: return float(val)
    except (ValueError, TypeError): return None

# ── Pages ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, prefill: Optional[int] = None):
    playlists = db.get_playlists()
    prefill_track = None
    if prefill:
        prefill_track = db.get_track(prefill)
        
    recent_tracks = db.get_library(limit=15)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "playlists": playlists,
        "page": "generate",
        "prefill": prefill_track,
        "recent_tracks": recent_tracks,
    })

@app.get("/remix", response_class=HTMLResponse)
async def remix(request: Request, prefill: Optional[int] = None):
    playlists = db.get_playlists()
    prefill_track = None
    if prefill:
        prefill_track = db.get_track(prefill)
        
    recent_tracks = db.get_library(limit=15)
    return templates.TemplateResponse("remix.html", {
        "request": request,
        "playlists": playlists,
        "page": "remix",
        "prefill": prefill_track,
        "recent_tracks": recent_tracks,
    })


@app.get("/inpaint", response_class=HTMLResponse)
async def inpaint(request: Request, prefill: Optional[int] = None):
    playlists = db.get_playlists()
    prefill_track = None
    if prefill:
        prefill_track = db.get_track(prefill)

    recent_tracks = db.get_library(limit=15)
    return templates.TemplateResponse("inpaint.html", {
        "request": request,
        "playlists": playlists,
        "page": "inpaint",
        "prefill": prefill_track,
        "recent_tracks": recent_tracks,
    })


@app.get("/library", response_class=HTMLResponse)
async def library(
    request: Request,
    q: str = "",
    liked: bool = False,
    sort: str = "created_at",
    order: str = "desc",
    page: int = 1,
    page_size: int = 50,
):
    all_tracks = db.get_library(search=q, liked_only=liked, sort_by=sort, order=order)

    total = len(all_tracks)
    total_pages = max(1, (total + page_size - 1) // page_size)
    cur_page = max(1, min(page, total_pages))
    offset = (cur_page - 1) * page_size
    tracks = all_tracks[offset: offset + page_size]

    # Fix layout break by truncating long prompts for processing tasks
    for t in tracks:
        if t.get("status") != "complete":
            p_str = t.get("prompt") or ""
            t["prompt"] = p_str[:80] + "..." if len(p_str) > 80 else p_str

    playlists = db.get_playlists()
    return templates.TemplateResponse("library.html", {
        "request": request,
        "tracks": tracks,
        "playlists": playlists,
        "search": q,
        "liked_only": liked,
        "sort": sort,
        "order": order.lower(),
        "total": total,
        "total_pages": total_pages,
        "cur_page": cur_page,
        "page": "library",
    })
# 1. Add the GET route for the new page
@app.get("/lora", response_class=HTMLResponse)
async def lora_page(request: Request):
    playlists = db.get_playlists()
    return templates.TemplateResponse("lora.html", {
        "request": request,
        "page": "lora",
        "playlists": playlists,
    })

# 2. Add the POST route to handle the form submission
@app.post("/lora/load", response_class=HTMLResponse)
async def load_lora_action(
    request: Request,
    lora_path: str = Form(...),
    adapter_name: str = Form("custom_adapter"),
    strength: float = Form(1.0)
):
    try:
        # Strip quotes just in case user pasted "path"
        clean_path = lora_path.strip().strip('"').strip("'")
        
        resp = await ace.load_lora(
            lora_path=clean_path,
            adapter_name=adapter_name,
            strength=strength
        )
        
        msg = resp.get("message", "LoRA Loaded Successfully")
        
        # Return a success card
        return HTMLResponse(
            f"""<div class="success-card" style="padding:1rem; background:rgba(0,255,100,0.1); border:1px solid var(--accent); border-radius:4px; color:var(--text-main); margin-top:1rem;">
                  <div style="font-weight:600">✅ Success</div>
                  <div style="font-size:0.9rem; opacity:0.8">{msg}</div>
                  <div style="font-size:0.8rem; opacity:0.6; margin-top:0.5rem">Path: {clean_path}<br>Strength: {strength}</div>
                </div>"""
        )
        
    except Exception as e:
        return HTMLResponse(
            f"""<div class="error-card" style="margin-top:1rem;">
                  <span class="error-icon">⚠</span>
                  <strong>Failed to load LoRA</strong>
                  <p>{str(e)}</p>
                </div>"""
        )
@app.get("/playlists", response_class=HTMLResponse)
async def playlists_page(request: Request):
    playlists = db.get_playlists()
    return templates.TemplateResponse("playlists.html", {
        "request": request,
        "playlists": playlists,
        "page": "playlists",
    })

@app.get("/playlists/{playlist_id}", response_class=HTMLResponse)
async def playlist_detail(request: Request, playlist_id: int):
    playlist = db.get_playlist(playlist_id)
    if not playlist:
        raise HTTPException(404, "Playlist not found")
    tracks = db.get_playlist_tracks(playlist_id)
    playlists = db.get_playlists()
    return templates.TemplateResponse("playlist_detail.html", {
        "request": request,
        "playlist": playlist,
        "tracks": tracks,
        "playlists": playlists,
        "page": "playlists",
    })

# ── Status polling ───────────────────────────────────────────

@app.get("/status/{task_id}", response_class=HTMLResponse)
async def poll_status(request: Request, task_id: str, view: str = "card"):
    track = db.get_track_by_task(task_id)

    if not track:
        if view == "row":
            return HTMLResponse(f'<tr class="error-row"><td colspan="8">Task {task_id} not found</td></tr>')
        return HTMLResponse(f'<div class="error-card">Task {task_id} not found</div>')

    status = track.get("status", "pending")
    playlists = db.get_playlists()

    if status == "complete":
        template_name = "partials/track_card.html" if view == "card" else "partials/track_row.html"
        return templates.TemplateResponse(template_name, {
            "request": request,
            "track": track,
            "playlists": playlists,
            "search": "", "liked_only": False, "sort": "created_at", "order": "desc"
        })

    if status == "failed":
        if view == "row":
            return HTMLResponse('<tr class="error-row"><td colspan="8">⚠ Generation failed</td></tr>')
        return HTMLResponse(
            '<div class="error-card"><span class="error-icon">⚠</span><strong>Generation failed</strong></div>'
        )

    if status == "processing":
        prompt_str = track.get("prompt") or ""
        short_prompt = prompt_str[:80] + "..." if len(prompt_str) > 80 else prompt_str
        template_name = "partials/progress_card.html" if view == "card" else "partials/progress_row.html"
        return templates.TemplateResponse(template_name, {
            "request": request,
            "task_id": task_id,
            "prompt": short_prompt,
            "label": "FINALIZING AUDIO & ART..."
        })

    try:
        result = await ace.query_result(task_id)
        ace_status = result.get("status", 0)

        # Task not found in ACE-Step at all — check if the queue is empty,
        # which means the API crashed/restarted and lost the task
        if not result.get("found", True):
            server_stats = await ace.stats()
            queue_size = server_stats.get("queue_size", -1)
            # queue_size == 0 means nothing is running or queued → task is gone
            # queue_size == -1 means stats call itself failed → be conservative, keep polling
            if queue_size == 0:
                db.fail_track(task_id)
                error_html = (
                    '<div class="error-card">'
                    '<span class="error-icon">⚠</span>'
                    '<strong>Generation lost</strong>'
                    '<p style="font-size:0.8rem;opacity:0.7;margin-top:0.25rem">'
                    'ACE-Step queue is empty — the server may have restarted. Try regenerating.'
                    '</p></div>'
                )
                if view == "row":
                    return HTMLResponse(f'<tr class="error-row"><td colspan="8">{error_html}</td></tr>')
                return HTMLResponse(error_html)

        if ace_status == 1:
            with db._conn() as conn:
                conn.execute("UPDATE tracks SET status='processing' WHERE task_id=?", (task_id,))
            results = result.get("results", [])
            input_track = db.get_track_by_task(task_id)
            user_title = input_track.get("title")
            htmls = []

            # Safeguard title building to avoid crash on empty prompts
            safe_first_prompt = results[0].get("prompt", "") or ""
            base_title = user_title if user_title else db._make_title(safe_first_prompt)
            max_v = db.get_max_version(base_title, exclude_task_id=task_id)
            start_v = max_v + 1
            has_base = False
            if max_v == 0:
                with db._conn() as conn:
                    has_base = conn.execute("SELECT COUNT(*) FROM tracks WHERE title = ?", (base_title,)).fetchone()[0] > 0
            if has_base:
                start_v = max_v + 1  

            for i, r in enumerate(results):
                v = start_v + i
                title = base_title if max_v == 0 and len(results) == 1 and not has_base else f"{base_title} v{v}"

                # Fish robustly for metadata wherever the API decided to hide it
                metas = r.get("metas", {})
                raw = r.get("raw", {})
                
                extracted_bpm = metas.get("bpm") or raw.get("bpm")
                extracted_keyscale = metas.get("keyscale") or raw.get("keyscale") or raw.get("key_scale")
                extracted_timesig = metas.get("timesignature") or raw.get("timesignature") or raw.get("time_signature")
                extracted_duration = metas.get("duration") or raw.get("duration")

                prompt = r.get("prompt") or raw.get("prompt") or ""
                lyrics = r.get("lyrics") or raw.get("lyrics") or ""
                seed_val = r.get("seed_value") or raw.get("seed_value") or ""

                raw_name = r.get("audio_url", "").split("path=")[-1] if "path=" in r.get("audio_url", "") else ""
                raw_name = urllib.parse.unquote(raw_name)
                raw_name = osp.basename(raw_name.replace("\\", "/"))
                local_filename = raw_name if raw_name else f"{task_id}_{i}.{input_track.get('audio_format', 'mp3')}"
                dest_path = str(AUDIO_DIR / local_filename)

                if r.get("audio_url"):
                    await ace.download_audio(r["audio_url"], dest_path)
                    
                current_task_id = task_id if i == 0 else str(uuid.uuid4())

                style = input_track.get("cover_art", "algorithmic")
                # Issue 2: cover art runs fire-and-forget so it doesn't block the
                # status response. The card renders without a cover first; it shows
                # on the next page load once the background task finishes.
                asyncio.create_task(_update_cover_art(current_task_id, style))
                image_path = ""  # updated async

                if i == 0:
                    db.complete_track(
                        task_id=current_task_id,
                        local_filename=local_filename,
                        prompt=prompt,
                        lyrics=lyrics,
                        bpm=extracted_bpm,
                        key_scale=extracted_keyscale,
                        time_signature=extracted_timesig,
                        duration=extracted_duration,
                        seed_value=seed_val,
                        image_path=image_path,
                    )
                    with db._conn() as conn:
                        conn.execute("UPDATE tracks SET title=? WHERE task_id=?", (title, current_task_id))
                    track = db.get_track_by_task(current_task_id)
                else:
                    db.create_track(
                        task_id=current_task_id,
                        prompt=prompt,
                        lyrics=lyrics,
                        title=title,
                        vocal_language=input_track["vocal_language"],
                        batch_size=1,
                        inference_steps=input_track["inference_steps"],
                        guidance_scale=input_track["guidance_scale"],
                        shift=input_track["shift"],
                        input_seed=seed_val,
                        audio_format=input_track["audio_format"],
                        thinking=bool(input_track["thinking"]),
                        use_cot_caption=bool(input_track["use_cot_caption"]),
                        use_cot_language=bool(input_track["use_cot_language"]),
                        lm_temperature=input_track["lm_temperature"],
                        lm_cfg_scale=input_track["lm_cfg_scale"],
                        lm_top_k=input_track["lm_top_k"],
                        lm_top_p=input_track["lm_top_p"],
                        lm_repetition_penalty=input_track["lm_repetition_penalty"],
                        cover_art=style,
                    )
                    db.complete_track(
                        task_id=current_task_id,
                        local_filename=local_filename,
                        prompt=prompt,
                        lyrics=lyrics,
                        bpm=extracted_bpm,
                        key_scale=extracted_keyscale,
                        time_signature=extracted_timesig,
                        duration=extracted_duration,
                        seed_value=seed_val,
                        image_path=image_path,
                    )
                    track = db.get_track_by_task(current_task_id)

                template_name = "partials/track_card.html" if view == "card" else "partials/track_row.html"
                card_html = templates.TemplateResponse(template_name, {
                    "request": request,
                    "track": track,
                    "playlists": playlists,
                    "search": "", "liked_only": False, "sort": "created_at", "order": "desc"
                }).body.decode('utf-8')
                htmls.append(card_html)

            # Issue 4: reverse so newest track (last created) appears first in the
            # queue, matching the library's default created_at DESC sort order.
            # Without this, v1 appears above v2 in the live queue but below it
            # after a page refresh — a jarring flip.
            return HTMLResponse(''.join(reversed(htmls)))

        if ace_status == 2:
            db.fail_track(task_id)
            if view == "row":
                return HTMLResponse('<tr class="error-row"><td colspan="8">⚠ Generation failed</td></tr>')
            return HTMLResponse('<div class="error-card"><span class="error-icon">⚠</span><strong>Generation failed</strong></div>')

    except Exception as e:
        import traceback
        traceback.print_exc()
        if track.get("status") == "pending":
            with db._conn() as conn:
                conn.execute("UPDATE tracks SET status='pending' WHERE task_id=?", (task_id,))

    prompt_str = track.get("prompt") or ""
    short_prompt = prompt_str[:80] + "..." if len(prompt_str) > 80 else prompt_str
    template_name = "partials/progress_card.html" if view == "card" else "partials/progress_row.html"
    return templates.TemplateResponse(template_name, {
        "request": request,
        "task_id": task_id,
        "prompt": short_prompt,
        "label": "GENERATING"
    })

@app.post("/generate", response_class=HTMLResponse)
async def generate(
    request: Request,
    title: Optional[str] = Form(None),
    prompt: str = Form(...),
    lyrics: str = Form(""),
    audio_duration: Optional[str] = Form(None),
    bpm: Optional[str] = Form(None),
    key_scale: str = Form("auto"),
    time_signature: str = Form("4"),
    vocal_language: str = Form("auto"),
    batch_size: int = Form(2),
    inference_steps: int = Form(50),
    guidance_scale_str: str = Form("7.0"),
    shift_str: str = Form("3"),
    seed_str: str = Form("-1"),
    audio_format: str = Form("mp3"),
    thinking: bool = Form(False),
    use_cot_caption: bool = Form(False),
    use_cot_language: bool = Form(False),
    lm_temperature: float = Form(0.85),
    lm_cfg_scale: float = Form(2.5),
    lm_top_k: int = Form(0),
    lm_top_p: float = Form(0.9),
    lm_repetition_penalty: float = Form(1.0),
    cover_art: str = Form("algorithmic"),
    task_type: str = Form("text2music"),
    audio_cover_strength: float = Form(1.0),
    cover_noise_strength: float = Form(0.0),
    audio_code_string: str = Form(""),
    reference_audio: Optional[UploadFile] = File(None),
    src_audio: Optional[UploadFile] = File(None),
    repainting_start: float = Form(0.0),
    repainting_end_str: str = Form(""),
    chunk_mask_explicit: bool = Form(False),
    caption_scale: float = Form(1.0),
    lyrics_scale: float = Form(1.0),
    llm_codes_scale: float = Form(1.0),
    audio_influence_scale: float = Form(1.0),
):
    audio_duration_val = safe_int(audio_duration)
    bpm_val = safe_int(bpm)
    key_scale = "" if key_scale.lower() == "auto" or not key_scale else key_scale
    time_signature = "" if time_signature.lower() == "auto" or not time_signature else time_signature
    vocal_language = "" if vocal_language.lower() == "auto" or not vocal_language else vocal_language
    guidance_scale = safe_float(guidance_scale_str)
    shift = safe_float(shift_str)
    def parse_seed(val: str):
        if not val or val.strip() == "-1":
            return -1
        parts = [safe_int(p.strip()) for p in val.split(",")]
        parts = [p for p in parts if p is not None]
        if not parts:
            return -1
        return parts if len(parts) > 1 else parts[0]

    seed = parse_seed(seed_str)
    lm_top_k_input = lm_top_k
    lm_top_p_input = lm_top_p
    lm_top_k = None if lm_top_k == 0 else lm_top_k
    lm_top_p = None if lm_top_p >= 1 else lm_top_p
    title = title.strip() if title else None

    ref_bytes = await reference_audio.read() if reference_audio and reference_audio.filename else None
    src_bytes = await src_audio.read() if src_audio and src_audio.filename else None
    
    ref_name = reference_audio.filename if reference_audio else "ref.mp3"
    src_name = src_audio.filename if src_audio else "src.mp3"

    # repainting_end: empty / "-1" → None (ace_client will send -1 for inpaint tasks)
    repainting_end: Optional[float] = None
    if repainting_end_str.strip() and repainting_end_str.strip() != "-1":
        try:
            repainting_end = float(repainting_end_str.strip())
        except ValueError:
            pass

    chunk_mask_mode = "explicit" if chunk_mask_explicit else "auto"

    try:
        task_id = await ace.release_task(
            prompt=prompt,
            lyrics=lyrics,
            audio_duration=audio_duration_val,
            bpm=bpm_val,
            key_scale=key_scale,
            time_signature=time_signature,
            vocal_language=vocal_language,
            batch_size=batch_size,
            inference_steps=inference_steps,
            guidance_scale=guidance_scale,
            shift=shift,
            seed=seed,
            audio_format=audio_format,
            thinking=thinking,
            use_cot_caption=use_cot_caption,
            use_cot_language=use_cot_language,
            lm_temperature=lm_temperature,
            lm_cfg_scale=lm_cfg_scale,
            lm_top_k=lm_top_k,
            lm_top_p=lm_top_p,
            lm_repetition_penalty=lm_repetition_penalty,
            task_type=task_type,
            audio_cover_strength=audio_cover_strength,
            cover_noise_strength=cover_noise_strength,
            audio_code_string=audio_code_string,
            reference_audio=ref_bytes,
            src_audio=src_bytes,
            ref_filename=ref_name,
            src_filename=src_name,
            repainting_start=repainting_start,
            repainting_end=repainting_end,
            chunk_mask_mode=chunk_mask_mode,
            caption_scale=caption_scale,
            lyrics_scale=lyrics_scale,
            llm_codes_scale=llm_codes_scale,
            audio_influence_scale=audio_influence_scale,
        )
    except Exception as e:
        return HTMLResponse(
            f"""<div class="error-card">
                  <span class="error-icon">⚠</span>
                  <strong>Could not reach ACE-Step API</strong>
                  <p>{str(e)}</p>
                </div>""",
            status_code=503,
        )

    db.create_track(
        task_id=task_id,
        title=title,
        prompt=prompt,
        lyrics=lyrics,
        vocal_language=vocal_language or "auto",
        batch_size=batch_size,
        inference_steps=inference_steps,
        guidance_scale=guidance_scale,
        shift=shift,
        input_seed=seed_str,
        audio_format=audio_format,
        thinking=bool(thinking) if not audio_code_string.strip() else False,
        use_cot_caption=use_cot_caption,
        use_cot_language=use_cot_language,
        lm_temperature=lm_temperature,
        lm_cfg_scale=lm_cfg_scale,
        lm_top_k=lm_top_k_input,
        lm_top_p=lm_top_p_input,
        lm_repetition_penalty=lm_repetition_penalty,
        cover_art=cover_art
    )

    prompt_str = prompt or ""
    short_prompt = prompt_str[:80] + "..." if len(prompt_str) > 80 else prompt_str
    return templates.TemplateResponse("partials/progress_card.html", {
        "request": request,
        "task_id": task_id,
        "prompt": short_prompt,
    })


@app.post("/extract_codes", response_class=HTMLResponse)
async def extract_codes(extract_audio: UploadFile = File(...)):
    if not extract_audio.filename:
        return HTMLResponse(
            '<span id="extract-indicator" style="color:var(--error-color,#f66)">No file selected.</span>'
        )

    src_bytes = await extract_audio.read()

    try:
        task_id = await ace.release_task(
            prompt="",
            task_type="extract",
            src_audio=src_bytes,
            src_filename=extract_audio.filename,
            extract_codes_only=True
        )
    except Exception as e:
        return HTMLResponse(
            f'<span id="extract-indicator" style="color:var(--error-color,#f66)">Error: {str(e)}</span>'
            '<script>document.querySelectorAll(".extract-btn").forEach(b=>b.disabled=false)</script>'
        )

    # Return a self-polling div — no blocked worker, user can navigate away
    return HTMLResponse(f"""
        <div id="extract-indicator"
             hx-get="/extract_status/{task_id}?type=codes"
             hx-trigger="every 3s"
             hx-target="this"
             hx-swap="outerHTML">
          <span style="color:var(--text-muted);font-size:0.85rem">⟳ Extracting codes… (may take a few minutes)</span>
        </div>
    """)


@app.post("/extract_metadata", response_class=HTMLResponse)
async def extract_metadata(extract_audio: UploadFile = File(...)):
    if not extract_audio.filename:
        return HTMLResponse('<span id="extract-indicator"></span>')

    src_bytes = await extract_audio.read()

    try:
        task_id = await ace.release_task(
            prompt="",
            task_type="extract",
            src_audio=src_bytes,
            src_filename=extract_audio.filename,
            full_analysis_only=True
        )
    except Exception as e:
        return HTMLResponse(
            f'<span id="extract-indicator" style="color:var(--error-color,#f66)">Error: {str(e)}</span>'
            '<script>document.querySelectorAll(".extract-btn").forEach(b=>b.disabled=false)</script>'
        )

    return HTMLResponse(f"""
        <div id="extract-indicator"
             hx-get="/extract_status/{task_id}?type=metadata"
             hx-trigger="every 3s"
             hx-target="this"
             hx-swap="outerHTML">
          <span style="color:var(--text-muted);font-size:0.85rem">⟳ Analyzing track… (may take a few minutes)</span>
        </div>
    """)


_RE_ENABLE = '<script>document.querySelectorAll(".extract-btn").forEach(b=>b.disabled=false)</script>'

@app.get("/extract_status/{task_id}", response_class=HTMLResponse)
async def extract_status(task_id: str, type: str = "codes"):
    """Client-side polling target for extraction tasks."""
    try:
        res = await ace.query_result(task_id)
        status = res.get("status", 0)

        if status == 1:
            results = res.get("results", [])

            if type == "codes":
                r = results[0] if results else {}
                codes = r.get("audio_codes") or r.get("raw", {}).get("audio_codes") or ""
                if codes:
                    return HTMLResponse(
                        f'<span id="extract-indicator" style="color:var(--accent);font-size:0.85rem">✓ Codes extracted</span>{_RE_ENABLE}',
                        headers={"HX-Trigger": json.dumps({"codesExtracted": {"codes": codes}})}
                    )
                return HTMLResponse(
                    f'<span id="extract-indicator" style="color:var(--error-color,#f66)">No codes in response</span>{_RE_ENABLE}'
                )

            else:  # metadata
                r = results[0] if results else {}
                metas = r.get("metas", {})
                raw = r.get("raw", {})
                trigger_data = {
                    "prompt":         r.get("prompt") or raw.get("prompt") or "",
                    "bpm":            metas.get("bpm") or raw.get("bpm") or "",
                    "key_scale":      metas.get("keyscale") or raw.get("keyscale") or raw.get("key_scale") or "",
                    "time_signature": metas.get("timesignature") or raw.get("timesignature") or raw.get("time_signature") or "",
                    "audio_duration": metas.get("duration") or raw.get("duration") or "",
                }
                trigger_data = {k: v for k, v in trigger_data.items() if v}
                return HTMLResponse(
                    f'<span id="extract-indicator" style="color:var(--accent);font-size:0.85rem">✓ Metadata extracted</span>{_RE_ENABLE}',
                    headers={"HX-Trigger": json.dumps({"autoFillForm": trigger_data})}
                )

        if status == 2:
            return HTMLResponse(
                f'<span id="extract-indicator" style="color:var(--error-color,#f66)">Extraction failed</span>{_RE_ENABLE}'
            )

        # Still pending — return another self-polling div
        label = "Extracting codes" if type == "codes" else "Analyzing track"
        return HTMLResponse(f"""
            <div id="extract-indicator"
                 hx-get="/extract_status/{task_id}?type={type}"
                 hx-trigger="every 3s"
                 hx-target="this"
                 hx-swap="outerHTML">
              <span style="color:var(--text-muted);font-size:0.85rem">⟳ {label}… (may take a few minutes)</span>
            </div>
        """)

    except Exception as e:
        return HTMLResponse(
            f'<span id="extract-indicator" style="color:var(--error-color,#f66)">Error: {str(e)}</span>{_RE_ENABLE}'
        )


# ── Audio proxy ──────────────────────────────────────────────

@app.get("/audio/{task_id}")
async def get_audio(task_id: str):
    track = db.get_track_by_task(task_id)
    if not track or not track.get("audio_path"):
        raise HTTPException(404, "Audio not found")

    local_path = AUDIO_DIR / track["audio_path"]
    if not local_path.exists():
        raise HTTPException(404, f"Audio file not on disk: {track['audio_path']}")

    media_type = "audio/mpeg"
    if str(local_path).endswith(".wav"):
        media_type = "audio/wav"
    elif str(local_path).endswith(".flac"):
        media_type = "audio/flac"

    return FileResponse(
        path=str(local_path),
        media_type=media_type,
        headers={"Accept-Ranges": "bytes"},
    )


# ── Player partial ───────────────────────────────────────────

@app.get("/player/{task_id}", response_class=HTMLResponse)
async def get_player(
    request: Request, 
    task_id: str,
    playlist_id: Optional[int] = None,
    q: str = "",
    liked: bool = False,
    sort: str = "created_at",
    order: str = "desc"
):
    track = db.get_track_by_task(task_id)
    if not track:
        raise HTTPException(404)
        
    prev_id, next_id = db.get_neighbors(
        task_id, playlist_id=playlist_id, search=q, liked_only=liked, sort_by=sort, order=order
    )
    
    params = {}
    if playlist_id: params["playlist_id"] = playlist_id
    if q: params["q"] = q
    if liked: params["liked"] = "true"
    params["sort"] = sort
    params["order"] = order
    qs = urllib.parse.urlencode(params)

    return templates.TemplateResponse("partials/player_bar.html", {
        "request": request,
        "track": track,
        "prev_id": prev_id,
        "next_id": next_id,
        "qs": qs
    })


@app.post("/tracks/{task_id}/listen")
async def register_listen(task_id: str):
    db.increment_listens(task_id)
    return HTMLResponse("")


# ── Track actions ────────────────────────────────────────────

@app.get("/tracks/{task_id}/cover-img", response_class=HTMLResponse)
async def cover_img(task_id: str):
    """Polled by track_card when image_path is empty. Returns the <img> tag
    once cover art is ready (self-destructs the poller), or re-renders the
    polling placeholder to keep checking."""
    track = db.get_track_by_task(task_id)
    if track and track.get("image_path"):
        return HTMLResponse(
            f'<img src="/static/covers/{track["image_path"]}" '
            f'style="width: 48px; height: 48px; border-radius: 4px; object-fit: cover; margin-right: 1rem;">'
        )
    # Not ready yet — return a fresh polling div (same id, keeps triggering)
    return HTMLResponse(
        f'<div id="cover-pending-{task_id}" '
        f'style="width: 48px; height: 48px; border-radius: 4px; background: var(--bg-surface-2); flex-shrink: 0; margin-right: 1rem;" '
        f'hx-get="/tracks/{task_id}/cover-img" '
        f'hx-trigger="every 3s" '
        f'hx-target="this" '
        f'hx-swap="outerHTML" '
        f'hx-push-url="false">'
        f'</div>'
    )



@app.get("/tracks/{track_id}/download")
async def download_track(track_id: int):
    track = db.get_track(track_id)
    if not track or not track.get("audio_path"):
        raise HTTPException(404, "Track not found")

    local_path = AUDIO_DIR / track["audio_path"]
    if not local_path.exists():
        raise HTTPException(404, "Audio file not on disk")

    ext = local_path.suffix or ".mp3"
    safe_title = "".join(c for c in (track.get("title") or "track") if c.isalnum() or c in " _-").strip()
    download_name = f"{safe_title}{ext}"

    media_type = "audio/mpeg"
    if ext == ".wav":  media_type = "audio/wav"
    elif ext == ".flac": media_type = "audio/flac"

    return FileResponse(
        path=str(local_path),
        media_type=media_type,
        filename=download_name,
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


@app.get("/tracks/{track_id}", response_class=HTMLResponse)
async def track_detail(request: Request, track_id: int):
    track = db.get_track(track_id)
    if not track:
        raise HTTPException(404, "Track not found")
    playlists = db.get_playlists()
    return templates.TemplateResponse("track_detail.html", {
        "request": request,
        "track": track,
        "playlists": playlists,
        "page": "library",
    })


@app.post("/tracks/{track_id}/like", response_class=HTMLResponse)
async def toggle_like(track_id: int):
    liked = db.toggle_like(track_id)
    cls = "like-btn active" if liked else "like-btn"
    icon = "♥" if liked else "♡"
    return HTMLResponse(
        f'<button class="{cls}" hx-post="/tracks/{track_id}/like" '
        f'hx-target="this" hx-swap="outerHTML" hx-push-url="false">{icon}</button>'
    )


@app.post("/tracks/{track_id}/add-to-playlist", response_class=HTMLResponse)
async def add_to_playlist(track_id: int, playlist_id: int = Form(...)):
    db.add_to_playlist(playlist_id, track_id)
    return HTMLResponse('<span class="toast-inline">✓ Added</span>')


@app.post("/tracks/{track_id}/remove-from-playlist/{playlist_id}", response_class=HTMLResponse)
async def remove_from_playlist(track_id: int, playlist_id: int):
    db.remove_from_playlist(playlist_id, track_id)
    return HTMLResponse(
        f'<tr id="track-row-{track_id}" '
        f'style="display:none" hx-swap-oob="outerHTML:#track-row-{track_id}"></tr>'
    )


@app.post("/tracks/{track_id}/delete", response_class=HTMLResponse)
async def delete_track(track_id: int):
    db.delete_track(track_id)
    return HTMLResponse("")


# ── Playlist actions ─────────────────────────────────────────

@app.post("/playlists")
async def create_playlist(name: str = Form(...), description: str = Form("")):
    playlist_id = db.create_playlist(name, description)
    return RedirectResponse(f"/playlists/{playlist_id}", status_code=303)


@app.post("/playlists/{playlist_id}/delete")
async def delete_playlist(playlist_id: int):
    db.delete_playlist(playlist_id)
    return RedirectResponse("/playlists", status_code=303)