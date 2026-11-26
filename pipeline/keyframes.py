import base64
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from pipeline.common import (
    OUTPUTS_DIR,
    compute_input_hash,
    load_and_validate_storyboard,
    log_run,
)

PROJECT_ROOT = OUTPUTS_DIR.parent
KEYFRAMES_DIR = OUTPUTS_DIR / "keyframes"


def _load_env_file() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _render_clean_scene_fallback(
    out_path: Path,
    shot_index: int = 1,
    width: int = 1280,
    height: int = 720,
    label: str = "",
) -> str:
    """Render a smooth, warm, zero-static scene when remote AI image generation fails."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw, ImageFilter

        palettes = [
            ((46, 20, 10), (198, 104, 34), (255, 206, 114)),
            ((24, 36, 56), (172, 94, 42), (250, 190, 98)),
            ((58, 24, 12), (214, 126, 44), (255, 222, 140)),
            ((30, 26, 42), (160, 86, 48), (242, 180, 96)),
        ]
        c_top, c_bottom, c_glow = palettes[(shot_index - 1) % len(palettes)]

        img = Image.new("RGBA", (width, height), (*c_top, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        steps = 48
        band_h = max(1, height // steps)
        for i in range(steps):
            t = i / max(1, steps - 1)
            r = int(c_top[0] * (1 - t) + c_bottom[0] * t)
            g = int(c_top[1] * (1 - t) + c_bottom[1] * t)
            b = int(c_top[2] * (1 - t) + c_bottom[2] * t)
            y0 = i * band_h
            y1 = height if i == steps - 1 else (i + 1) * band_h
            draw.rectangle([0, y0, width, y1], fill=(r, g, b, 255))

        gx = int(width * (0.45 + 0.08 * math.sin(shot_index)))
        gy = int(height * (0.42 + 0.06 * math.cos(shot_index)))
        r_outer = int(min(width, height) * 0.36)
        r_inner = int(min(width, height) * 0.15)
        draw.ellipse([gx - r_outer, gy - r_outer, gx + r_outer,
                     gy + r_outer], fill=(*c_glow, 70))
        draw.ellipse([gx - r_inner, gy - r_inner, gx + r_inner,
                     gy + r_inner], fill=(255, 234, 180, 120))

        horizon_y = int(height * 0.68)
        hill_pts = [(0, height)]
        for x in range(0, width + 64, 64):
            hy = horizon_y - \
                int(28 * math.sin((x / max(1, width)) * math.pi * 2 + shot_index))
            hill_pts.append((x, hy))
        hill_pts.append((width, height))
        draw.polygon(hill_pts, fill=(24, 13, 8, 180))

        img = img.filter(ImageFilter.GaussianBlur(radius=16))

        if label:
            draw_sharp = ImageDraw.Draw(img, "RGBA")
            draw_sharp.text((32, height - 44),
                            label[:85], fill=(255, 244, 218, 225))

        img.convert("RGB").save(str(out_path), format="PNG")
        return "pillow_warm_scene_fallback"
    except Exception:
        bg_hex = "0x9c4e1c" if shot_index % 2 == 1 else "0x364f6b"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={bg_hex}:s={width}x{height}:d=1",
                "-frames:v",
                "1",
                str(out_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return "ffmpeg_warm_color_fallback"


def _generate_cloudflare_image(prompt: str, model: str) -> bytes:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    api_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    if not account_id or not api_token:
        raise RuntimeError(
            "Missing CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN in .env")

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    payload = {"prompt": prompt}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Cloudflare HTTP {exc.code}: {body[:250]}") from exc

    if raw.startswith(b"\x89PNG") or raw.startswith(b"\xff\xd8"):
        return raw

    parsed = json.loads(raw.decode("utf-8"))
    if isinstance(parsed, dict) and isinstance(parsed.get("result"), dict):
        img_b64 = parsed["result"].get("image")
        if img_b64:
            return base64.b64decode(img_b64)

    raise RuntimeError(f"Unexpected Cloudflare response: {str(parsed)[:200]}")


def _normalize_to_png(src_bytes: bytes, out_path: Path, width: int, height: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = out_path.with_suffix(".tmp_img")
    tmp_file.write_bytes(src_bytes)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(tmp_file),
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},format=rgb24",
                "-frames:v",
                "1",
                str(out_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        if tmp_file.exists():
            tmp_file.unlink()


def run_keyframes_stage(force: bool = False) -> dict[str, Path]:
    _load_env_file()
    storyboard = load_and_validate_storyboard()
    KEYFRAMES_DIR.mkdir(parents=True, exist_ok=True)

    style_anchor = storyboard.get("style_anchor", "").strip()
    model = (
        os.getenv("CF_IMAGE_MODEL")
        or os.getenv("CLOUDFLARE_IMAGE_MODEL")
        or "@cf/black-forest-labs/flux-1-schnell"
    ).strip()
    width, height = 1280, 720
    outputs: dict[str, Path] = {}

    for idx, shot in enumerate(storyboard["shots"], start=1):
        shot_id = shot["id"]
        raw_prompt = (
            shot.get("visual_prompt")
            or shot.get("image_prompt")
            or shot.get("subtitle_en")
            or ""
        ).strip()
        full_prompt = f"{style_anchor}. {raw_prompt}".strip(". ")
        seed = int(shot.get("seed", 42 + idx))

        kf_hash = compute_input_hash(
            {
                "stage": "keyframes",
                "shot_id": shot_id,
                "prompt": full_prompt,
                "seed": seed,
                "model": model,
                "v": 3,
            }
        )
        out_path = KEYFRAMES_DIR / f"{shot_id}_{kf_hash}.png"

        if not force and out_path.exists() and out_path.stat().st_size > 2048:
            outputs[shot_id] = out_path
            log_run(
                {
                    "stage": "keyframes",
                    "shot_id": shot_id,
                    "status": "cache_hit",
                    "input_hash": kf_hash,
                    "seed": seed,
                    "output": str(out_path.relative_to(PROJECT_ROOT)),
                    "latency_ms": 0,
                }
            )
            continue

        start = time.perf_counter()
        last_err = ""
        api_ok = False

        for attempt in range(2):
            try:
                img_bytes = _generate_cloudflare_image(full_prompt, model)
                _normalize_to_png(img_bytes, out_path, width, height)
                api_ok = True
                break
            except Exception as exc:
                last_err = str(exc)[:300]
                if attempt < 1:
                    time.sleep(0.5)

        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        if api_ok:
            log_run(
                {
                    "stage": "keyframes",
                    "shot_id": shot_id,
                    "status": "ok",
                    "model": model,
                    "input_hash": kf_hash,
                    "seed": seed,
                    "output": str(out_path.relative_to(PROJECT_ROOT)),
                    "latency_ms": latency_ms,
                }
            )
        else:
            print(
                f"[keyframes] {shot_id} API failed ({last_err}) -> using clean fallback")
            fb_model = _render_clean_scene_fallback(
                out_path,
                shot_index=idx,
                width=width,
                height=height,
                label=f"{shot_id}: {raw_prompt[:60]}",
            )
            log_run(
                {
                    "stage": "keyframes",
                    "shot_id": shot_id,
                    "status": "fallback_ok",
                    "model": fb_model,
                    "input_hash": kf_hash,
                    "seed": seed,
                    "output": str(out_path.relative_to(PROJECT_ROOT)),
                    "latency_ms": latency_ms,
                    "error": last_err,
                }
            )

        outputs[shot_id] = out_path

    return outputs


if __name__ == "__main__":
    force_flag = "--force" in sys.argv[1:]
    res = run_keyframes_stage(force=force_flag)
    print(f"Keyframes stage complete: {len(res)} images in {KEYFRAMES_DIR}")
