import base64
import subprocess
import time
from pathlib import Path
from typing import Any, Tuple

from google import genai

from pipeline.common import (
    OUTPUTS_DIR,
    call_with_retry,
    compute_input_hash,
    get_env_var,
    load_and_validate_storyboard,
    log_run,
)

AUDIO_DIR = OUTPUTS_DIR / "audio"
TTS_MODELS = ["gemini-3.8-flash"]


def _extract_audio_bytes(response: Any) -> bytes:
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline is not None:
                data = getattr(inline, "data", None)
                if isinstance(data, bytes) and len(data) > 200:
                    return data
                if isinstance(data, str) and len(data) > 200:
                    return base64.b64decode(data)
    raise ValueError("No inline audio bytes returned by Gemini TTS response")


def _generate_gemini_narration(text: str, language: str) -> Tuple[bytes, str]:
    api_key = get_env_var("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    prompt = (
        f"Read this narration clearly, calmly, and warmly in language '{language}'. "
        f"Do not add extra commentary:\n{text}"
    )

    errors: list[str] = []
    for model_name in TTS_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"response_modalities": ["AUDIO"]},
            )
            audio_bytes = _extract_audio_bytes(response)
            return audio_bytes, model_name
        except Exception as exc:
            errors.append(f"{model_name} -> {exc}")

    raise RuntimeError("Gemini TTS models failed -> " + " | ".join(errors))


def _generate_fallback_narration_wav(out_path: Path, duration_sec: float, seed: int) -> str:
    dur = max(2.0, float(duration_sec))
    freq = 180 + (abs(seed) % 45)
    fade_out_start = max(0.0, dur - 0.35)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={freq}:sample_rate=24000:duration={dur}",
        "-af",
        f"volume=0.03,afade=t=in:st=0:d=0.25,afade=t=out:st={fade_out_start:.2f}:d=0.3",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return "ffmpeg_fallback_tone_wav"


def run_narration_stage(force: bool = False, allow_fallback: bool = True) -> dict[str, Path]:
    storyboard = load_and_validate_storyboard()
    language = storyboard["language"]
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    for idx, shot in enumerate(storyboard["shots"], start=1):
        shot_id = shot["id"]
        text = shot["narration"].strip()
        duration_sec = float(shot["duration_sec"])
        seed = int(shot["seed"])
        nar_hash = compute_input_hash(
            {"shot_id": shot_id, "text": text,
                "language": language, "duration_sec": duration_sec}
        )
        out_path = AUDIO_DIR / f"narration_{shot_id}_{nar_hash}.wav"

        if not force and out_path.exists():
            outputs[shot_id] = out_path
            log_run(
                {
                    "stage": "narration",
                    "shot_id": shot_id,
                    "status": "cache_hit",
                    "input_hash": nar_hash,
                    "seed": seed,
                    "output": str(out_path.relative_to(OUTPUTS_DIR.parent)),
                    "latency_ms": 0,
                }
            )
            continue

        start = time.perf_counter()
        try:
            audio_bytes, used_model = call_with_retry(
                lambda t=text, lang=language: _generate_gemini_narration(
                    t, lang)
            )
            raw_tmp = AUDIO_DIR / f"_tmp_{shot_id}_{nar_hash}.bin"
            raw_tmp.write_bytes(audio_bytes)
            conv = subprocess.run(
                ["ffmpeg", "-y", "-i",
                    str(raw_tmp), "-ar", "24000", "-ac", "1", str(out_path)],
                capture_output=True,
                text=True,
            )
            if raw_tmp.exists():
                raw_tmp.unlink()
            if conv.returncode != 0 or not out_path.exists():
                raise RuntimeError(
                    f"FFmpeg audio normalize failed: {conv.stderr[:200]}")

            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            outputs[shot_id] = out_path
            log_run(
                {
                    "stage": "narration",
                    "shot_id": shot_id,
                    "status": "ok",
                    "model": used_model,
                    "input_hash": nar_hash,
                    "seed": seed,
                    "output": str(out_path.relative_to(OUTPUTS_DIR.parent)),
                    "latency_ms": latency_ms,
                }
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            if allow_fallback:
                fb_model = _generate_fallback_narration_wav(
                    out_path, duration_sec, seed + idx)
                outputs[shot_id] = out_path
                log_run(
                    {
                        "stage": "narration",
                        "shot_id": shot_id,
                        "status": "fallback_ok",
                        "model": fb_model,
                        "input_hash": nar_hash,
                        "seed": seed,
                        "output": str(out_path.relative_to(OUTPUTS_DIR.parent)),
                        "latency_ms": latency_ms,
                        "error": str(exc),
                    }
                )
            else:
                log_run(
                    {
                        "stage": "narration",
                        "shot_id": shot_id,
                        "status": "error",
                        "input_hash": nar_hash,
                        "seed": seed,
                        "latency_ms": latency_ms,
                        "error": str(exc),
                    }
                )
                raise

    return outputs


if __name__ == "__main__":
    nar_paths = run_narration_stage()
    print(f"Narration stage complete: {len(nar_paths)} files in {AUDIO_DIR}")
