import httpx
import asyncio
import json
from typing import Optional, AsyncIterator, Dict, List, Union

ACESTEP_BASE = "http://localhost:8001"

class AceStepClient:
    def __init__(self, base_url: str = ACESTEP_BASE):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        
    async def load_lora(self, lora_path: str, adapter_name: str = "default", strength: float = 1.0) -> dict:
        """
        Loads a LoRA adapter via the /v1/lora/load endpoint.
        """
        payload = {
            "lora_path": lora_path,
            "adapter_name": adapter_name,
            "strength": strength  # Sending strength in case backend supports merging/scaling
        }

        print("\n=== LoRA Load Request ===")
        print(json.dumps(payload, indent=2))
        print("=========================\n")

        async with httpx.AsyncClient(base_url=self.base_url, timeout=60.0) as client:
            # Note: The user prompt specified the endpoint is at /v1/lora/load
            # We assume self.base_url is the root (e.g. http://localhost:8001)
            resp = await client.post("/v1/lora/load", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def release_task(
        self,
        prompt: str,
        lyrics: str = "",
        audio_duration: Optional[float] = None,
        bpm: Optional[int] = None,
        key_scale: Optional[str] = None,
        time_signature: Optional[str] = None,
        vocal_language: Optional[str] = None,
        batch_size: int = 2,
        inference_steps: int = 50,
        guidance_scale: Optional[float] = None,
        shift: Optional[float] = None,
        seed: Union[int, List[int]] = -1,
        audio_format: str = "mp3",
        thinking: bool = True,
        use_cot_caption: bool = False,
        use_cot_language: bool = False,
        lm_temperature: float = 0.85,
        lm_cfg_scale: float = 2.5,
        lm_top_k: Optional[int] = None,
        lm_top_p: Optional[float] = None,
        lm_repetition_penalty: float = 1.0,
        task_type: str = "text2music",
        audio_cover_strength: float = 1.0,
        cover_noise_strength: float = 0.0,
        audio_code_string: str = "",
        reference_audio: Optional[bytes] = None,
        src_audio: Optional[bytes] = None,
        ref_filename: str = "ref.mp3",
        src_filename: str = "src.mp3",
        full_analysis_only: bool = False,
        extract_codes_only: bool = False,
        repainting_start: float = 0.0,
        repainting_end: Optional[float] = None,
        chunk_mask_mode: Optional[str] = None,
        caption_scale: float = 1.0,
        lyrics_scale: float = 1.0,
        llm_codes_scale: float = 1.0,
        audio_influence_scale: float = 1.0,
    ) -> str:
        
        # If user provides audio codes, force thinking to False
        if audio_code_string.strip():
            thinking = False

        payload = {
            "prompt": prompt,
            "lyrics": lyrics,
            "thinking": thinking,
            "use_cot_caption": use_cot_caption,
            "use_cot_language": use_cot_language,
            "lm_temperature": lm_temperature,
            "lm_cfg_scale": lm_cfg_scale,
            "lm_repetition_penalty": lm_repetition_penalty,
            "batch_size": batch_size,
            "inference_steps": inference_steps,
            "audio_format": audio_format,
            "task_type": task_type,
            "audio_cover_strength": audio_cover_strength,
            "cover_noise_strength": cover_noise_strength,
            "full_analysis_only": full_analysis_only,
            "extract_codes_only": extract_codes_only,
        }
        payload["caption_scale"] = caption_scale
        payload["lyrics_scale"] = lyrics_scale
        payload["llm_codes_scale"] = llm_codes_scale
        payload["audio_influence_scale"] = audio_influence_scale

        if task_type == "repaint":
            payload["repainting_start"] = repainting_start
            payload["repainting_end"] = repainting_end if repainting_end is not None else -1
            payload["chunk_mask_mode"] = chunk_mask_mode if chunk_mask_mode is not None else "explicit"
        
        if audio_code_string.strip():
            payload["audio_code_string"] = audio_code_string.strip()
        if audio_duration is not None:
            payload["audio_duration"] = audio_duration
        if bpm is not None:
            payload["bpm"] = bpm
        if key_scale is not None:
            payload["key_scale"] = key_scale
        if time_signature is not None:
            payload["time_signature"] = time_signature
        if vocal_language is not None:
            payload["vocal_language"] = vocal_language
        if guidance_scale is not None:
            payload["guidance_scale"] = guidance_scale
        if shift is not None:
            payload["shift"] = shift
        print("Seed value:", seed)

        if seed is not None and seed != -1:
            if isinstance(seed, list):
                payload["seed"] = ",".join(str(s) for s in seed)  # → "1024,2048" for form compat
            else:
                payload["seed"] = seed
            payload["use_random_seed"] = False
        else:
            payload["use_random_seed"] = True
        if lm_top_k is not None:
            payload["lm_top_k"] = lm_top_k
        if lm_top_p is not None:
            payload["lm_top_p"] = lm_top_p

        print("\n=== ACE-Step API Request Payload ===")
        print(json.dumps(payload, indent=2))
        print("====================================\n")

        files = {}
        if reference_audio:
            files["reference_audio"] = (ref_filename, reference_audio, "audio/mpeg")
        if src_audio:
            files["src_audio"] = (src_filename, src_audio, "audio/mpeg")

        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
            if files:
                form_data = {}
                for k, v in payload.items():
                    if isinstance(v, bool):
                        form_data[k] = "true" if v else "false"
                    elif v is not None:
                        form_data[k] = str(v)
                resp = await client.post("/release_task", data=form_data, files=files)
            else:
                resp = await client.post("/release_task", json=payload)
                
            resp.raise_for_status()
            body = resp.json()

        data = body.get("data") or {}
        task_id: str = data.get("task_id", "")
        if not task_id:
            raise ValueError(f"No task_id in /release_task response. Full body: {body}")
        return task_id

    async def stats(self) -> Dict:
        """Fetch /v1/stats — used to detect if the queue is empty after a crash."""
        try:
            resp = await self._client.get("/v1/stats", timeout=5.0)
            resp.raise_for_status()
            return (resp.json().get("data") or {})
        except Exception:
            return {}

    async def query_result(self, task_id: str) -> Dict:
        resp = await self._client.post(
            "/query_result",
            json={"task_id_list": [task_id]},
        )
        resp.raise_for_status()
        body = resp.json()

        items: list = body.get("data") or []
        if not items:
            # Task not found in ACE-Step's memory at all — different from "queued"
            return {"status": 0, "found": False}

        item = items[0]
        status: int = item.get("status", 0)

        # ADDED: Debug print when task finishes (success or fail) to avoid polling spam
        if status in (1, 2):
            print(f"\n=== ACE-Step API Response (Task {task_id} - Status {status}) ===")
            print(json.dumps(item, indent=2))
            print("========================================================\n")

        if status != 1:
            return {"status": status, "found": True, "raw": item}

        raw_result = item.get("result", "[]")
        try:
            results = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
        except json.JSONDecodeError:
            results = []

        if isinstance(results, dict):
            results = [results]

        if not results:
            return {"status": 2, "error": "Empty result list"}

        parsed_results = []
        for r in results:
            metas: dict = r.get("metas") or {}
            parsed_results.append({
                "audio_url": r.get("file", ""),
                "metas": metas,
                "prompt": r.get("prompt", ""),
                "lyrics": r.get("lyrics", ""),
                "seed_value": r.get("seed_value", ""),
                "audio_codes": r.get("audio_codes", ""),  # Mapped audio codes
                "status_message": r.get("status_message", ""),
                "raw": r,
            })

        return {
            "status": 1,
            "results": parsed_results
        }

    async def poll_until_complete(
        self, task_id: str, interval: float = 2.0
    ) -> AsyncIterator[dict]:
        while True:
            result = await self.query_result(task_id)
            yield result
            if result.get("status") in (1, 2):
                break
            await asyncio.sleep(interval)

    async def download_audio(self, audio_url: str, dest_path: str) -> None:
        url = f"{self.base_url}{audio_url}"
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(dest_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        f.write(chunk)

    async def stream_audio(self, audio_url: str) -> AsyncIterator[bytes]:
        url = f"{self.base_url}{audio_url}"
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    yield chunk

    async def health(self) -> bool:
        try:
            resp = await self._client.get("/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        await self._client.aclose()