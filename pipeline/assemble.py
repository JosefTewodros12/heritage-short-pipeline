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
from pipeline.music import run_music_stage
from pipeline.narration import run_narration_stage
from pipeline.shots import run_shots_stage

FINAL_DIR = OUTPUTS_DIR / "final"
WORK_DIR = OUTPUTS_DIR / "_work"


def _format_srt_time(seconds: float) -> str:
    ms_total = max(0, int(round(seconds * 1000)))
    hours = ms_total // 3_600_000
    rem = ms_total % 3_600_000
    minutes = rem // 60_000
    rem %= 60_000
    secs = rem // 1000
    millis = rem % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _write_srt(shots: list[dict[str, Any]], srt_path: Path) -> None:
    lines: list[str] = []
    cursor = 0.0
    for idx, shot in enumerate(shots, start=1):
        dur = float(shot["duration_sec"])
        start_t = _format_srt_time(cursor)
        end_t = _format_srt_time(cursor + dur)
        text = shot.get("subtitle_en", "").strip()
        lines.append(f"{idx}\n{start_t} --> {end_t}\n{text}\n")
        cursor += dur
    srt_path.write_text("\n".join(lines), encoding="utf-8")


def _build_end_card(end_card_path: Path, title: str, duration_sec: float = 3.0) -> None:
    clean_title = title.replace(":", "").replace("'", "")
    filter_expr = (
        f"drawtext=text='{clean_title}':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=(h/2)-45,"
        f"drawtext=text='Made with AI (Gemini + FFmpeg Pipeline)':fontcolor=#e09f3e:fontsize=24:x=(w-text_w)/2:y=(h/2)+15,"
        f"format=yuv420p"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=#14110f:s=1280x720:d={duration_sec:.2f}:r=24",
        "-vf",
        filter_expr,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(end_card_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not end_card_path.exists():
        fallback_cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=#14110f:s=1280x720:d={duration_sec:.2f}:r=24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(end_card_path),
        ]
        subprocess.run(fallback_cmd, check=True,
                       capture_output=True, text=True)


def _concat_videos(clip_paths: list[Path], out_video: Path) -> None:
    list_file = WORK_DIR / "concat_clips.txt"
    content = "\n".join(
        f"file '{p.resolve().as_posix()}'" for p in clip_paths) + "\n"
    list_file.write_text(content, encoding="utf-8")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "24",
        str(out_video),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _mix_narration_and_score(
    narration_paths: list[Path],
    score_path: Path,
    total_duration_sec: float,
    out_wav: Path,
) -> None:
    nar_concat_list = WORK_DIR / "concat_narration.txt"
    nar_concat_list.write_text(
        "\n".join(
            f"file '{p.resolve().as_posix()}'" for p in narration_paths) + "\n",
        encoding="utf-8",
    )
    joined_nar = WORK_DIR / "joined_narration.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(nar_concat_list),
            "-ar",
            "44100",
            "-ac",
            "2",
            str(joined_nar),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    filter_complex = (
        f"[1:a]atrim=0:{total_duration_sec:.2f},asetpts=PTS-STARTPTS,volume=0.55[music];"
        f"[0:a]apad=whole_dur={total_duration_sec:.2f},volume=1.15[voice];"
        f"[music][voice]sidechaincompress=threshold=0.02:ratio=6:attack=300:release=1500[ducked];"
        f"[voice][ducked]amix=inputs=2:duration=first:dropout_transition=2,"
        f"loudnorm=I=-14:TP=-1.0:LRA=11[norm]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(joined_nar),
        "-i",
        str(score_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[norm]",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(out_wav),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _export_aspect_ratio(
    base_video: Path,
    mixed_audio: Path,
    out_mp4: Path,
    aspect_ratio: str,
) -> None:
    if aspect_ratio == "9:16":
        vf = (
            "[0:v]scale=720:1280:force_original_aspect_ratio=increase,"
            "crop=720:1280,boxblur=20:5[bg];"
            "[0:v]scale=720:-1[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[vout]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(base_video),
            "-i",
            str(mixed_audio),
            "-filter_complex",
            vf,
            "-map",
            "[vout]",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-preset",
            "medium",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(out_mp4),
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(base_video),
            "-i",
            str(mixed_audio),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-preset",
            "medium",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(out_mp4),
        ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def run_assemble_stage(force: bool = False) -> dict[str, Path]:
    storyboard = load_and_validate_storyboard()
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    clips = run_shots_stage(force=force)
    narrations = run_narration_stage(force=force)
    score_path = run_music_stage(force=force)

    shots = storyboard["shots"]
    clip_list = [clips[s["id"]] for s in shots]
    nar_list = [narrations[s["id"]] for s in shots]
    total_dur = sum(float(s["duration_sec"]) for s in shots) + 3.0

    asm_hash = compute_input_hash(
        {
            "title": storyboard["title"],
            "clips": [p.name for p in clip_list],
            "narrations": [p.name for p in nar_list],
            "score": score_path.name,
            "total_dur": round(total_dur, 2),
        }
    )

    out_16x9 = FINAL_DIR / f"film_16x9_{asm_hash}.mp4"
    out_9x16 = FINAL_DIR / f"film_9x16_{asm_hash}.mp4"
    latest_16x9 = FINAL_DIR / "film_16x9.mp4"
    latest_9x16 = FINAL_DIR / "film_9x16.mp4"
    srt_path = FINAL_DIR / "subtitles_en.srt"

    _write_srt(shots, srt_path)

    if not force and out_16x9.exists() and out_9x16.exists():
        latest_16x9.write_bytes(out_16x9.read_bytes())
        latest_9x16.write_bytes(out_9x16.read_bytes())
        log_run(
            {
                "stage": "assemble",
                "status": "cache_hit",
                "input_hash": asm_hash,
                "duration_sec": round(total_dur, 2),
                "outputs": [
                    str(latest_16x9.relative_to(OUTPUTS_DIR.parent)),
                    str(latest_9x16.relative_to(OUTPUTS_DIR.parent)),
                ],
                "latency_ms": 0,
            }
        )
        return {"16:9": latest_16x9, "9:16": latest_9x16}

    start = time.perf_counter()
    try:
        end_card_path = WORK_DIR / "end_card.mp4"
        _build_end_card(end_card_path, storyboard["title"], duration_sec=3.0)

        base_video = WORK_DIR / "base_timeline.mp4"
        _concat_videos(clip_list + [end_card_path], base_video)

        mixed_wav = WORK_DIR / "mixed_audio.wav"
        _mix_narration_and_score(nar_list, score_path, total_dur, mixed_wav)

        _export_aspect_ratio(base_video, mixed_wav, out_16x9, "16:9")
        _export_aspect_ratio(base_video, mixed_wav, out_9x16, "9:16")

        latest_16x9.write_bytes(out_16x9.read_bytes())
        latest_9x16.write_bytes(out_9x16.read_bytes())

        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        log_run(
            {
                "stage": "assemble",
                "status": "ok",
                "input_hash": asm_hash,
                "duration_sec": round(total_dur, 2),
                "outputs": [
                    str(latest_16x9.relative_to(OUTPUTS_DIR.parent)),
                    str(latest_9x16.relative_to(OUTPUTS_DIR.parent)),
                ],
                "latency_ms": latency_ms,
            }
        )
        return {"16:9": latest_16x9, "9:16": latest_9x16}
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        log_run(
            {
                "stage": "assemble",
                "status": "error",
                "input_hash": asm_hash,
                "duration_sec": round(total_dur, 2),
                "latency_ms": latency_ms,
                "error": str(exc),
            }
        )
        raise


if __name__ == "__main__":
    exports = run_assemble_stage(force=True)
    print("Assembled exports:", {k: str(v) for k, v in exports.items()})
