import base64
import subprocess
import time
from pathlib import Path
from typing import Tuple

import requests

from pipeline.common import (
    OUTPUTS_DIR,
    call_with_retry,
    compute_input_hash,
    get_env_var,
    load_and_validate_storyboard,
    log_run,
)

KEYFRAMES_DIR = OUTPUTS_DIR / "keyframes"
FLUX_MODELS = [
    "@cf/black-forest-labs/flux-1-schnell",
    "@cf/black-forest-labs/flux-2-klein-4b",
    "@cf/black-forest-labs/flux-2-klein-9b",
    "@cf/bytedance/sdxl-lightning",
]


def _decode_image_bytes(response: requests.Response) -> bytes:
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        payload = response.json()
        result = payload.get("result", payload)
        if isinstance(result, dict) and "image" in result:
            img_val = result["image"]
            if isinstance(img_val, str):
                return base64.b64decode(img_val)
        raise ValueError(
            f"Unexpected JSON response from Cloudflare Workers AI: {list(payload.keys())}")
    return response.content


def _generate_cloudflare_keyframe(prompt: str, seed: int) -> Tuple[bytes, str]:
    account_id = get_env_var("CLOUDFLARE_ACCOUNT_ID")
    api_token = get_env_var("CLOUDFLARE_API_TOKEN")
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    errors: list[str] = []
    for model in FLUX_MODELS:
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
        body = {"prompt": prompt, "seed": seed, "width": 1280, "height": 720}
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=120)
            if not resp.ok:
                raise RuntimeError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}")
            img_bytes = _decode_image_bytes(resp)
            if len(img_bytes) < 1000:
                raise ValueError("Returned image bytes too small")
            return img_bytes, model
        except Exception as exc:
            errors.append(f"{model} -> {exc}")

    raise RuntimeError(
        "All Cloudflare image models failed -> " + " | ".join(errors))


def _generate_ffmpeg_fallback_keyframe(out_path: Path, shot_id: str, seed: int) -> str:
    palette = [
        ("0x2b1b12", "0xd9822b"),
        ("0x1e242b", "0xe09f3e"),
        ("0x2e1a14", "0xc86d2d"),
        ("0x1c252c", "0x8ab17d"),
    ]
    bg_hex, accent_hex = palette[abs(seed) % len(palette)]
    safe_label = shot_id.replace(":", "").replace("'", "")

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={bg_hex}:s=1280x720:d=1",
        "-f",
        "lavfi",
        "-i",
        f"color=c={accent_hex}@0.25:s=640x360:d=1",
        "-filter_complex",
        f"[0:v][1:v]overlay=320:180,drawtext=text='{safe_label} (fallback still)':fontcolor=white:fontsize=36:x=(w-text_w)/2:y=(h-text_h)/2",
        "-frames:v",
        "1",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.exists():
        # Simpler fallback without drawtext if libfreetype isn't compiled in
        simple_cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={bg_hex}:s=1280x720:d=1",
            "-frames:v",
            "1",
            str(out_path),
        ]
        subprocess.run(simple_cmd, check=True, capture_output=True, text=True)
    return "ffmpeg_fallback_still"


def run_keyframes_stage(force: bool = False, allow_fallback: bool = True) -> dict[str, Path]:
    storyboard = load_and_validate_storyboard()
    style_anchor = storyboard["style_anchor"]
    KEYFRAMES_DIR.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    for shot in storyboard["shots"]:
        shot_id = shot["id"]
        full_prompt = f"{style_anchor}. {shot['image_prompt']}"
        seed = int(shot["seed"])
        shot_hash = compute_input_hash(
            {"prompt": full_prompt, "seed": seed, "w": 1280, "h": 720})
        out_path = KEYFRAMES_DIR / f"{shot_id}_{shot_hash}.png"

        if not force and out_path.exists():
            outputs[shot_id] = out_path
            log_run(
                {
                    "stage": "keyframes",
                    "shot_id": shot_id,
                    "status": "cache_hit",
                    "input_hash": shot_hash,
                    "seed": seed,
                    "output": str(out_path.relative_to(OUTPUTS_DIR.parent)),
                    "latency_ms": 0,
                }
            )
            continue

        start = time.perf_counter()
        try:
            img_bytes, used_model = call_with_retry(
                lambda p=full_prompt, s=seed: _generate_cloudflare_keyframe(
                    p, s)
            )
            out_path.write_bytes(img_bytes)
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            outputs[shot_id] = out_path
            log_run(
                {
                    "stage": "keyframes",
                    "shot_id": shot_id,
                    "status": "ok",
                    "model": used_model,
                    "input_hash": shot_hash,
                    "seed": seed,
                    "output": str(out_path.relative_to(OUTPUTS_DIR.parent)),
                    "latency_ms": latency_ms,
                }
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            if allow_fallback:
                fallback_model = _generate_ffmpeg_fallback_keyframe(
                    out_path, shot_id, seed)
                outputs[shot_id] = out_path
                log_run(
                    {
                        "stage": "keyframes",
                        "shot_id": shot_id,
                        "status": "fallback_ok",
                        "model": fallback_model,
                        "input_hash": shot_hash,
                        "seed": seed,
                        "output": str(out_path.relative_to(OUTPUTS_DIR.parent)),
                        "latency_ms": latency_ms,
                        "error": str(exc),
                    }
                )
            else:
                log_run(
                    {
                        "stage": "keyframes",
                        "shot_id": shot_id,
                        "status": "error",
                        "input_hash": shot_hash,
                        "seed": seed,
                        "latency_ms": latency_ms,
                        "error": str(exc),
                    }
                )
                raise

    return outputs


if __name__ == "__main__":
    paths = run_keyframes_stage()
    print(f"Keyframes stage complete: {len(paths)} files in {KEYFRAMES_DIR}")
