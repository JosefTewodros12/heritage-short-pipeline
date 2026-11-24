import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from dotenv import load_dotenv
from jsonschema import validate

ROOT_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT_DIR / "schema" / "storyboard.schema.json"
STORYBOARD_PATH = ROOT_DIR / "storyboard.json"
RUNS_LOG_PATH = ROOT_DIR / "runs.jsonl"
OUTPUTS_DIR = ROOT_DIR / "outputs"

load_dotenv(ROOT_DIR / ".env")


def load_and_validate_storyboard(
    storyboard_path: Path = STORYBOARD_PATH,
    schema_path: Path = SCHEMA_PATH,
) -> dict[str, Any]:
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validate(instance=storyboard, schema=schema)
    return storyboard


def compute_input_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def log_run(entry: dict[str, Any], log_path: Path = RUNS_LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **entry}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def call_with_retry(
    fn: Callable[[], Any],
    max_attempts: int = 3,
    base_delay_sec: float = 1.5,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> Any:
    last_err: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_err = exc
            if attempt < max_attempts:
                if on_retry:
                    on_retry(attempt, exc)
                time.sleep(base_delay_sec * attempt)
    raise RuntimeError(
        f"Failed after {max_attempts} attempts: {last_err}") from last_err


def get_env_var(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise EnvironmentError(
            f"Missing required environment variable: {name}")
    return value
