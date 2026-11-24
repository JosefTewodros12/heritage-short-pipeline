# Pipeline Architecture

## Contract & Stages

All stages read from `storyboard.json` and validate it against `schema/storyboard.schema.json`:

- `pipeline/common.py`: Loads `.env`, validates `storyboard.json`, hashes inputs (`compute_input_hash`), retries transient errors (`call_with_retry`), and appends logs to `runs.jsonl`.
- `pipeline/script.py`: Caches and refines narration and subtitles (`gemini-3.8-flash`) with a storyboard pass-through fallback.
- `pipeline/keyframes.py`: Generates `1280x720` PNG keyframes in `outputs/keyframes/` with caching, retries, and an `ffmpeg` fallback still.
- `pipeline/narration.py`: Generates per-shot narration WAV files in `outputs/audio/` with caching, retries, and fallback WAV synthesis.
- `pipeline/music.py`: Generates a warm score WAV sized to total film duration in `outputs/audio/`, cached by input hash.
- `pipeline/shots.py`: Animates each keyframe into a 24 fps H.264 clip in `outputs/clips/` using `ffmpeg` motion.
- `pipeline/assemble.py`: Builds `subtitles_en.srt`, renders a 3-second AI disclosure end card, ducks the score under narration (`sidechaincompress`), normalizes loudness (`loudnorm`), and exports `outputs/final/film_16x9.mp4` and `outputs/final/film_9x16.mp4`.
- `pipeline/run_pipeline.py`: Runs validation and all stages end to end (`--force` supported).

## Caching, Retries & Fallbacks

- Output filenames embed a SHA-256 input hash so unchanged shots hit the cache (`cache_hit`).
- Transient failures use retries and log errors to `runs.jsonl` while fallbacks keep pipeline runs moving.
