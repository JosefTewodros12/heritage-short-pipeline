# Failure Journal

## 1. Gemini Model Availability (`404 NOT_FOUND` on `gemini-2.5-flash`)

- **What happened:** Calling `gemini-2.5-flash` returned HTTP `404 NOT_FOUND` stating the model is no longer available to new users and pointing to `gemini-3.8-flash`[cite: 4, 6].
- **What we tried:** Updated `MODEL_CANDIDATES` in `pipeline/script.py` to target `gemini-3.8-flash` and cleaned up `.env` formatting so API keys had no leading whitespace after `=`.
- **Workaround & current status:** Added retry logic (`call_with_retry`) and a storyboard pass-through fallback in `pipeline/script.py` so stage execution and `runs.jsonl` logging continue without halting the pipeline when an API call or model endpoint fails.

## 2. Cloudflare Workers AI Image Models (`410 Gone` & `400 Bad Input` / `7000 No route`)

- **What happened:** `@cf/stabilityai/stable-diffusion-xl-base-1.0` returned `410 Client Error: Gone` (model retired)[cite: 6]. Testing `@cf/black-forest-labs/flux-1-schnell` returned `HTTP 400` (`code: 5006`) rejecting `/seed, /width, /height` JSON fields; `@cf/black-forest-labs/flux-2-klein-4b` and `flux-2-klein-9b` returned `HTTP 400` (`code: 5006`) requiring `multipart`; and `@cf/bytedance/sdxl-lightning` returned `HTTP 400` (`code: 7000`, `No route for that URI`).
- **What we tried:** Queried multiple Workers AI image model endpoints with retries and detailed error capture in `pipeline/keyframes.py`.
- **Workaround & current status:** Added an `ffmpeg` fallback keyframe generator (`ffmpeg_fallback_still`) and logged every failure and latency in `runs.jsonl` so all 8 shots still produce valid `1280x720` PNG keyframes for assembly[cite: 5, 10, 13].

## 3. Local Windows Shell & `make` Availability

- **What happened:** Pasting shell commands into `pipeline/common.py` initially caused syntax issues, and Windows PowerShell does not always include GNU `make` by default.
- **What we tried:** Separated Python stage modules under `pipeline/`, verified with `python -m pipeline.run_pipeline`, and kept `Makefile` for environments with `make` installed[cite: 5, 9, 10].
