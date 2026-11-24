import subprocess
import time
from pathlib import Path
from typing import Any

from pipeline.common import (
    OUTPUTS_DIR,
    compute_input_hash,
    load_and_validate_storyboard,
    log_run,
)

AUDIO_DIR = OUTPUTS_DIR / "audio"


def _compute_total_duration(storyboard: dict[str, Any]) -> float:
    total = sum(float(shot["duration_sec"]) for shot in storyboard["shots"])
    return max(10.0, total + 3.0)


def _synthesize_warm_score(out_path: Path, duration_sec: float, seed: int) -> str:
    f1 = 130.81 + (abs(seed) % 12)
    f2 = f1 * 1.498
    f3 = f1 * 2.0
    fade_out_start = max(1.0, duration_sec - 2.5)

    filter_expr = (
        f"[0:a]volume=0.06[a0];"
        f"[1:a]volume=0.04[a1];"
        f"[2:a]volume=0.025[a2];"
        f"[a0][a1][a2]amix=inputs=3:duration=first,"
        f"lowpass=f=650,"
        f"afade=t=in:st=0:d=2.0,"
        f"afade=t=out:st={fade_out_start:.2f}:d=2.2"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={f1:.2f}:sample_rate=44100:duration={duration_sec:.2f}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={f2:.2f}:sample_rate=44100:duration={duration_sec:.2f}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={f3:.2f}:sample_rate=44100:duration={duration_sec:.2f}",
        "-filter_complex",
        filter_expr,
        "-ac",
        "2",
        "-ar",
        "44100",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return "ffmpeg_warm_instrumental_score"


def run_music_stage(force: bool = False) -> Path:
    storyboard = load_and_validate_storyboard()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    total_dur = _compute_total_duration(storyboard)
    seed = int(storyboard["shots"][0]["seed"]) if storyboard["shots"] else 42

    score_payload = {
        "title": storyboard["title"],
        "duration_sec": round(total_dur, 2),
        "shot_count": len(storyboard["shots"]),
        "seed": seed,
    }
    score_hash = compute_input_hash(score_payload)
    out_path = AUDIO_DIR / f"score_{score_hash}.wav"

    if not force and out_path.exists():
        log_run(
            {
                "stage": "music",
                "status": "cache_hit",
                "input_hash": score_hash,
                "seed": seed,
                "duration_sec": round(total_dur, 2),
                "output": str(out_path.relative_to(OUTPUTS_DIR.parent)),
                "latency_ms": 0,
            }
        )
        return out_path

    start = time.perf_counter()
    try:
        model_name = _synthesize_warm_score(out_path, total_dur, seed)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        log_run(
            {
                "stage": "music",
                "status": "ok",
                "model": model_name,
                "input_hash": score_hash,
                "seed": seed,
                "duration_sec": round(total_dur, 2),
                "output": str(out_path.relative_to(OUTPUTS_DIR.parent)),
                "latency_ms": latency_ms,
            }
        )
        return out_path
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        log_run(
            {
                "stage": "music",
                "status": "error",
                "input_hash": score_hash,
                "seed": seed,
                "latency_ms": latency_ms,
                "error": str(exc),
            }
        )
        raise


if __name__ == "__main__":
    score_file = run_music_stage()
    print(f"Music stage complete: {score_file}")
