import subprocess
import time
from pathlib import Path
from typing import Any

from pipeline.common import (
    OUTPUTS_DIR,
    compute_input_hash,
    log_run,
    load_and_validate_storyboard,
)
from pipeline.keyframes import run_keyframes_stage

CLIPS_DIR = OUTPUTS_DIR / "clips"


def _build_zoompan_filter(motion_prompt: str, duration_sec: float, fps: int = 24) -> str:
    motion_l = (motion_prompt or "").lower()
    total_frames = max(24, int(round(duration_sec * fps)))

    if "zoom-out" in motion_l or "pull-back" in motion_l or "pull back" in motion_l:
        # Zoom out gently from 1.15x to 1.0x
        z_expr = f"1.15-0.15*(on/{total_frames})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif "pan left" in motion_l:
        z_expr = "1.10"
        x_expr = f"(iw-iw/zoom)*(1-(on/{total_frames}))"
        y_expr = "ih/2-(ih/zoom/2)"
    elif "pan right" in motion_l:
        z_expr = "1.10"
        x_expr = f"(iw-iw/zoom)*(on/{total_frames})"
        y_expr = "ih/2-(ih/zoom/2)"
    else:
        # Default gentle push-in / zoom-in from 1.0x to 1.12x
        z_expr = f"1.0+0.12*(on/{total_frames})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    return (
        f"scale=1920:1080,"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={total_frames}:s=1280x720:fps={fps},"
        f"format=yuv420p"
    )


def _render_motion_clip(keyframe_path: Path, out_path: Path, motion_prompt: str, duration_sec: float) -> str:
    vf = _build_zoompan_filter(motion_prompt, duration_sec, fps=24)
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(keyframe_path),
        "-vf",
        vf,
        "-t",
        f"{duration_sec:.2f}",
        "-r",
        "24",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return "ffmpeg_ken_burns_zoompan"


def run_shots_stage(force: bool = False, keyframes: dict[str, Path] | None = None) -> dict[str, Path]:
    storyboard = load_and_validate_storyboard()
    if keyframes is None:
        keyframes = run_keyframes_stage(force=False)

    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    for shot in storyboard["shots"]:
        shot_id = shot["id"]
        kf_path = keyframes[shot_id]
        duration_sec = float(shot["duration_sec"])
        motion_prompt = shot["motion_prompt"]
        seed = int(shot["seed"])

        kf_bytes_hash = compute_input_hash(
            {
                "shot_id": shot_id,
                "keyframe": kf_path.name,
                "duration_sec": duration_sec,
                "motion_prompt": motion_prompt,
                "seed": seed,
            }
        )
        out_path = CLIPS_DIR / f"{shot_id}_{kf_bytes_hash}.mp4"

        if not force and out_path.exists():
            outputs[shot_id] = out_path
            log_run(
                {
                    "stage": "shots",
                    "shot_id": shot_id,
                    "status": "cache_hit",
                    "input_hash": kf_bytes_hash,
                    "seed": seed,
                    "output": str(out_path.relative_to(OUTPUTS_DIR.parent)),
                    "latency_ms": 0,
                }
            )
            continue

        start = time.perf_counter()
        try:
            model_name = _render_motion_clip(
                kf_path, out_path, motion_prompt, duration_sec)
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            outputs[shot_id] = out_path
            log_run(
                {
                    "stage": "shots",
                    "shot_id": shot_id,
                    "status": "ok",
                    "model": model_name,
                    "input_hash": kf_bytes_hash,
                    "seed": seed,
                    "output": str(out_path.relative_to(OUTPUTS_DIR.parent)),
                    "latency_ms": latency_ms,
                }
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            log_run(
                {
                    "stage": "shots",
                    "shot_id": shot_id,
                    "status": "error",
                    "input_hash": kf_bytes_hash,
                    "seed": seed,
                    "latency_ms": latency_ms,
                    "error": str(exc),
                }
            )
            raise

    return outputs


if __name__ == "__main__":
    clip_paths = run_shots_stage()
    print(f"Shots stage complete: {len(clip_paths)} clips in {CLIPS_DIR}")
