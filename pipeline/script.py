import json
import time
from typing import Any

from google import genai

from pipeline.common import (
    OUTPUTS_DIR,
    call_with_retry,
    compute_input_hash,
    get_env_var,
    load_and_validate_storyboard,
    log_run,
)

CACHE_PATH = OUTPUTS_DIR / "script_cache.json"
MODEL_CANDIDATES = ["gemini-3.8-flash"]


def _polish_with_gemini(storyboard: dict[str, Any]) -> tuple[dict[str, Any], str]:
    api_key = get_env_var("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    prompt = (
        "Review and lightly refine the narration and English subtitles for this short heritage film storyboard "
        "without changing shot IDs, durations, seeds, or visual prompts. Return valid JSON only matching "
        '{"title": str, "shots": [{"id": str, "narration": str, "subtitle_en": str}]}.\n\n'
        + json.dumps(
            {
                "title": storyboard["title"],
                "language": storyboard["language"],
                "shots": [
                    {
                        "id": s["id"],
                        "duration_sec": s["duration_sec"],
                        "narration": s["narration"],
                        "subtitle_en": s["subtitle_en"],
                    }
                    for s in storyboard["shots"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    errors: list[str] = []
    for model_name in MODEL_CANDIDATES:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            raw_text = (response.text or "").strip()
            parsed = json.loads(raw_text)
            return parsed, model_name
        except Exception as exc:
            errors.append(f"{model_name} -> {exc}")

    raise RuntimeError("Gemini script models failed -> " + " | ".join(errors))


def _fallback_storyboard_result(storyboard: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": storyboard["title"],
        "language": storyboard["language"],
        "aspect_ratios": storyboard["aspect_ratios"],
        "style_anchor": storyboard["style_anchor"],
        "shots": [dict(s) for s in storyboard["shots"]],
    }


def run_script_stage(force: bool = False, allow_fallback: bool = True) -> dict[str, Any]:
    storyboard = load_and_validate_storyboard()
    payload = {
        "title": storyboard["title"],
        "language": storyboard["language"],
        "shots": [
            {
                "id": s["id"],
                "duration_sec": s["duration_sec"],
                "narration": s["narration"],
                "subtitle_en": s["subtitle_en"],
            }
            for s in storyboard["shots"]
        ],
    }
    input_hash = compute_input_hash(payload)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    if not force and CACHE_PATH.exists():
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if cached.get("input_hash") == input_hash:
            log_run(
                {
                    "stage": "script",
                    "status": "cache_hit",
                    "input_hash": input_hash,
                    "latency_ms": 0,
                }
            )
            return cached["data"]

    start = time.perf_counter()
    try:
        refined, used_model = call_with_retry(
            lambda: _polish_with_gemini(storyboard))
        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        refined_map = {item["id"]: item for item in refined.get(
            "shots", []) if "id" in item}
        merged_shots = []
        for shot in storyboard["shots"]:
            upd = refined_map.get(shot["id"], {})
            merged_shot = dict(shot)
            if upd.get("narration"):
                merged_shot["narration"] = upd["narration"]
            if upd.get("subtitle_en"):
                merged_shot["subtitle_en"] = upd["subtitle_en"]
            merged_shots.append(merged_shot)

        result = {
            "title": refined.get("title") or storyboard["title"],
            "language": storyboard["language"],
            "aspect_ratios": storyboard["aspect_ratios"],
            "style_anchor": storyboard["style_anchor"],
            "shots": merged_shots,
        }
        CACHE_PATH.write_text(
            json.dumps(
                {"input_hash": input_hash, "model": used_model, "data": result},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log_run(
            {
                "stage": "script",
                "status": "ok",
                "model": used_model,
                "input_hash": input_hash,
                "latency_ms": latency_ms,
            }
        )
        return result
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        if allow_fallback:
            result = _fallback_storyboard_result(storyboard)
            CACHE_PATH.write_text(
                json.dumps(
                    {"input_hash": input_hash,
                        "model": "storyboard_pass_through_fallback", "data": result},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            log_run(
                {
                    "stage": "script",
                    "status": "fallback_ok",
                    "model": "storyboard_pass_through_fallback",
                    "input_hash": input_hash,
                    "latency_ms": latency_ms,
                    "error": str(exc),
                }
            )
            return result

        log_run(
            {
                "stage": "script",
                "status": "error",
                "input_hash": input_hash,
                "latency_ms": latency_ms,
                "error": str(exc),
            }
        )
        raise


if __name__ == "__main__":
    data = run_script_stage()
    print(f"Script stage ready: {data['title']} ({len(data['shots'])} shots)")
