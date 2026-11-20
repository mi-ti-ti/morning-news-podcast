"""毎朝自動配信ニュースポッドキャスト メイン実行スクリプト"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from google import genai

from . import config
from .audio_generator import build_episode_mp3
from .news_collector import collect_all_news
from .rss_builder import build_rss_feed, cleanup_old_episodes
from .schema import JST, EpisodeScript
from .script_generator import generate_part_script


def _build_description(script: EpisodeScript) -> str:
    lines: list[str] = []

    if script.series_title:
        if script.series_episode_number is not None:
            lines.append(
                f"【シリーズ】{script.series_title}（第{script.series_episode_number}回）"
            )
        else:
            lines.append(f"【シリーズ】{script.series_title}")

    if script.weekly_theme:
        lines.append(f"【本日のテーマ】{script.weekly_theme}")

    if script.episode_type == "daily" and len(script.parts) == 2:
        part_labels = ["【第1部：経済ニュース】", "【第2部：ビジネスニュース】"]
        for label, part in zip(part_labels, script.parts):
            if lines:
                lines.append("")
            lines.append(label)
            lines.extend(f"・{b}" for b in part.summary_bullets)
    else:
        for idx, part in enumerate(script.parts, start=1):
            if lines:
                lines.append("")
            header = f"【{part.part_title}】" if len(script.parts) == 1 else f"【第{idx}部：{part.part_title}】"
            lines.append(header)
            lines.extend(f"・{b}" for b in part.summary_bullets)

    if script.keyword_of_the_day:
        if lines:
            lines.append("")
        lines.append(f"【今日の1ワード】{script.keyword_of_the_day}")

    return "\n".join(lines) if lines else script.title


def _refresh_feed() -> None:
    cleanup_old_episodes()
    build_rss_feed()


def _skip_if_existing(mp3_path: Path, force: bool, skip_feed: bool = False) -> bool:
    if mp3_path.exists() and not force:
        print(f"[INFO] {mp3_path.name} は既に生成済みのためスキップします（--force で再生成）。")
        if not skip_feed:
            _refresh_feed()
        return True
    return False


def _synthesize_and_publish(
    script: EpisodeScript, force: bool, skip_feed: bool = False
) -> None:
    mp3_path = config.EPISODES_DIR / f"{script.episode_id}.mp3"
    meta_path = config.EPISODES_DIR / f"{script.episode_id}.json"

    cutoff_date = datetime.now(JST).date() - timedelta(days=config.RETENTION_DAYS)
    if not script.keep_forever and script.published_at.date() < cutoff_date:
        print(
            f"[WARN] published_at ({script.published_at.date()}) が保持期間（{config.RETENTION_DAYS}日）より古いため、"
            "公開処理時のクリーンアップで削除されます。"
        )

    if _skip_if_existing(mp3_path, force, skip_feed=skip_feed):
        return

    duration_sec = build_episode_mp3([part.turns for part in script.parts], mp3_path)
    print(f"[INFO] MP3結合・保存完了: {mp3_path} ({duration_sec}秒)")

    meta = {
        "title": script.title,
        "description": _build_description(script),
        "duration_sec": duration_sec,
        "weekly_theme": script.weekly_theme,
        "keyword_of_the_day": script.keyword_of_the_day,
        "published_at": script.published_at.astimezone(JST).isoformat(),
        "episode_type": script.episode_type,
        "exclude_from_context": script.exclude_from_context,
        "keep_forever": script.keep_forever,
        "series_id": script.series_id,
        "series_title": script.series_title,
        "series_episode_number": script.series_episode_number,
    }
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    if not skip_feed:
        _refresh_feed()
    print("=== 処理が正常に完了しました ===")


def _generate_daily_script(now_jst: datetime) -> EpisodeScript:
    date_str = now_jst.strftime("%Y-%m-%d")
    date_label = now_jst.strftime("%Y年%m月%d日")
    weekly_theme = config.WEEKLY_THEMES.get(now_jst.weekday(), config.WEEKLY_THEMES[1])

    client = genai.Client()

    print(f"=== {date_label}（{weekly_theme['label']}）ポッドキャスト生成開始 ===")
    news = collect_all_news(client, weekly_theme)

    print("[INFO] 第1部（経済ニュース）の台本を生成中...")
    part1 = generate_part_script(
        client=client,
        part_number=1,
        news_briefing=news["economy"],
        date_label=date_label,
        weekly_theme=weekly_theme,
        past_context=news["past_context"],
        used_keywords=news["used_keywords"],
    )
    part1_chars = sum(len(t.text) for t in part1.turns)
    print(f"  -> 第1部台本完了: {len(part1.turns)}ターン / 約{part1_chars}文字")

    print("[INFO] 第2部（ビジネスニュース＆今日の1ワード）の台本を生成中...")
    part2 = generate_part_script(
        client=client,
        part_number=2,
        news_briefing=news["business"],
        date_label=date_label,
        weekly_theme=weekly_theme,
        past_context=news["past_context"],
        used_keywords=news["used_keywords"],
    )
    part2_chars = sum(len(t.text) for t in part2.turns)
    print(f"  -> 第2部台本完了: {len(part2.turns)}ターン / 約{part2_chars}文字")

    published_at = now_jst.replace(hour=5, minute=0, second=0, microsecond=0)
    return EpisodeScript(
        schema_version=1,
        episode_id=date_str,
        episode_type="daily",
        title=f"{date_label} | {part1.part_title} ほか",
        published_at=published_at,
        weekly_theme=weekly_theme["label"],
        keyword_of_the_day=part2.keyword_of_the_day,
        exclude_from_context=False,
        keep_forever=False,
        parts=[part1, part2],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Morning News Podcast Generator")
    parser.add_argument(
        "--force",
        action="store_true",
        help="対象エピソードのMP3が既に存在する場合でも上書き再生成する",
    )
    parser.add_argument(
        "--from-script",
        type=Path,
        default=None,
        help="台本JSONファイルを読み込み、Gemini APIを呼ばずに音声合成・公開を行う",
    )
    parser.add_argument(
        "--skip-feed",
        action="store_true",
        help="音声合成とメタデータ保存のみ行い、古いエピソード削除とfeed.xml再生成をスキップする",
    )
    parser.add_argument(
        "--refresh-feed-only",
        action="store_true",
        help="音声合成を行わず、古いエピソード削除とfeed.xml再生成のみ実行する",
    )
    args = parser.parse_args()

    if args.refresh_feed_only and (args.from_script is not None or args.skip_feed):
        parser.error("--refresh-feed-only は --from-script や --skip-feed と併用できません")

    if args.refresh_feed_only:
        print("=== RSSフィード再生成のみ実行 ===")
        _refresh_feed()
        print("=== 処理が正常に完了しました ===")
        return

    if args.from_script is not None:
        raw_json = args.from_script.read_text(encoding="utf-8")
        script = EpisodeScript.model_validate_json(raw_json)
        print(
            f"=== 台本JSONからの音声合成開始: {script.episode_id} "
            f"(type={script.episode_type}, parts={len(script.parts)}) ==="
        )
        _synthesize_and_publish(script, force=args.force, skip_feed=args.skip_feed)
        return

    now_jst = datetime.now(JST)
    date_str = now_jst.strftime("%Y-%m-%d")
    if _skip_if_existing(
        config.EPISODES_DIR / f"{date_str}.mp3", args.force, skip_feed=args.skip_feed
    ):
        return

    script = _generate_daily_script(now_jst)
    _synthesize_and_publish(script, force=args.force, skip_feed=args.skip_feed)


if __name__ == "__main__":
    main()
