# Costs, Latency & Quota Notes

## Free-Tier & Constraint Summary

- The pipeline is designed around zero-cost local/free tooling (`FFmpeg` locally, Gemini API free tier, Cloudflare Workers AI free allowance, and free GPU notebooks such as Kaggle/Colab when running heavy video/music weights)[cite: 6, 18, 19].
- On local CPU/FFmpeg execution for this run, direct API spend was `$0.00` (list-price equivalent for failed/fallback calls is `$0.00` for billed output since no billable image/video generation completed on those endpoints).

## Observed Telemetry from `runs.jsonl`

- **`keyframes` stage:** Cached shots (`shot_01`–`shot_04`) completed in `0 ms` (`cache_hit`). Uncached fallback shots (`shot_05`–`shot_08`) took roughly `10.19s` to `17.77s` per shot including API retry attempts before `ffmpeg` fallback generation.
- **`narration` & `music` stages:** Generated per-shot narration WAV files and the full-length instrumental score WAV locally via `FFmpeg` / stage runner, logged to `runs.jsonl`[cite: 5, 10].
- **`shots` & `assemble` stages:** Rendered 24 fps H.264 clips and exported both `outputs/final/film_16x9.mp4` and `outputs/final/film_9x16.mp4` with sidechain ducking and loudness normalization (`-14 LUFS`, `-1.0 dBTP`)[cite: 13, 15, 21].

## Quota & Scaling Advice

- Use input-hash caching so re-runs only regenerate changed shots (`cache_hit` = `0 ms` model latency).
- If running Wan 2.2 or ACE-Step 1.5 on Kaggle/Colab GPUs, draft at lower resolution, batch jobs, and track GPU minutes per stage[cite: 6, 7, 20].
