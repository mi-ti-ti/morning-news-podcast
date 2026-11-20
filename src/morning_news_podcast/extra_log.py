"""追加エピソード（extra）の依頼履歴をスリムな JSONL に追記するユーティリティ"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from . import config
from .schema import JST, resolve_published_at

DEFAULT_LOG_PATH = config.EXTRA_REQUESTS_LOG_PATH


def _resolve_jst_date(data: dict) -> str:
    episode_id = str(data.get("episode_id", "")).strip()
    dt = resolve_published_at(episode_id, data)
    if dt is None:
        raise ValueError(f"日付を特定できません: episode_id={episode_id!r}")
    return dt.astimezone(JST).strftime("%Y-%m-%d")


def load_logged_ids(log_path: Path) -> set[str]:
    if not log_path.exists():
        return set()

    logged_ids: set[str] = set()
    for line_no, line in enumerate(
        log_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError as exc:
            print(f"[WARN] 不正なJSONL行をスキップします ({log_path}:{line_no}): {exc}")
            continue
        if not isinstance(record, dict):
            print(
                f"[WARN] JSONオブジェクトではないJSONL行をスキップします ({log_path}:{line_no})"
            )
            continue
        episode_id = record.get("episode_id")
        if isinstance(episode_id, str) and episode_id:
            logged_ids.add(episode_id)
    return logged_ids


def append_extra_logs(
    script_paths: Iterable[Path],
    log_path: Path = DEFAULT_LOG_PATH,
) -> int:
    logged_ids = load_logged_ids(log_path)
    new_entries: list[dict[str, object]] = []

    for path in script_paths:
        if not path.exists():
            print(f"[WARN] スクリプトファイルが見つからないためスキップします: {path}")
            continue

        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("episode_type") != "extra":
            continue

        episode_id = str(data.get("episode_id", "")).strip()
        title = str(data.get("title", "")).strip()
        if not episode_id or not title:
            raise ValueError(f"episode_id または title が空です: {path}")

        if episode_id in logged_ids:
            continue

        entry: dict[str, object] = {
            "date": _resolve_jst_date(data),
            "episode_id": episode_id,
            "title": title,
        }
        series_id = data.get("series_id")
        if isinstance(series_id, str) and series_id.strip():
            entry["series_id"] = series_id.strip()
        series_ep_num = data.get("series_episode_number")
        if (
            isinstance(series_ep_num, int)
            and not isinstance(series_ep_num, bool)
            and series_ep_num >= 1
        ):
            entry["series_episode_number"] = series_ep_num

        new_entries.append(entry)
        logged_ids.add(episode_id)

    if not new_entries:
        return 0

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        for entry in new_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return len(new_entries)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Append extra episode request logs to JSONL."
    )
    parser.add_argument(
        "scripts",
        nargs="+",
        type=Path,
        help="Processed script JSON file paths",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"Output JSONL path (default: {DEFAULT_LOG_PATH})",
    )
    args = parser.parse_args()
    added = append_extra_logs(args.scripts, log_path=args.log_path)
    print(f"[INFO] 追加エピソードログに {added} 件追記しました: {args.log_path}")


if __name__ == "__main__":
    main()
