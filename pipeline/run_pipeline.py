import argparse

from pipeline.assemble import run_assemble_stage
from pipeline.common import load_and_validate_storyboard
from pipeline.keyframes import run_keyframes_stage
from pipeline.music import run_music_stage
from pipeline.narration import run_narration_stage
from pipeline.script import run_script_stage
from pipeline.shots import run_shots_stage


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Heritage Short film pipeline.")
    parser.add_argument("--force", action="store_true",
                        help="Force regeneration ignoring cache.")
    args = parser.parse_args()

    storyboard = load_and_validate_storyboard()
    print(
        f"Validated storyboard: '{storyboard['title']}' ({len(storyboard['shots'])} shots)")

    run_script_stage(force=args.force)
    run_keyframes_stage(force=args.force)
    run_narration_stage(force=args.force)
    run_music_stage(force=args.force)
    run_shots_stage(force=args.force)
    exports = run_assemble_stage(force=args.force)

    print("Pipeline finished successfully!")
    for ratio, path in exports.items():
        print(f"  [{ratio}] -> {path}")


if __name__ == "__main__":
    main()
