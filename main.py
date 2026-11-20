"""毎朝自動配信ニュースポッドキャスト メイン実行スクリプト"""

import argparse
import json
from datetime import datetime, timedelta, timezone

from google import genai

import config
from audio_generator import build_combined_mp3
from news_collector import collect_all_news
from rss_builder import build_rss_feed, cleanup_old_episodes
from script_generator import generate_part_script

JST = timezone(timedelta(hours=9))


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Morning News Podcast Generator")
    parser.add_argument(
        "--force",
        action="store_true",
        help="当日のMP3が既に存在する場合でも上書き再生成する",
    )
    args = parser.parse_args()

    now_jst = datetime.now(JST)
    date_str = now_jst.strftime("%Y-%m-%d")
    date_label = now_jst.strftime("%Y年%m月%d日")
    weekly_theme = config.WEEKLY_THEMES.get(now_jst.weekday(), config.WEEKLY_THEMES[1])

    mp3_path = config.EPISODES_DIR / f"{date_str}.mp3"
    meta_path = config.EPISODES_DIR / f"{date_str}.json"

    if mp3_path.exists() and not args.force:
        print(f"[INFO] {mp3_path.name} は既に生成済みのためスキップします（--force で再生成）。")
        cleanup_old_episodes()
        build_rss_feed()
        return

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

    duration_sec = build_combined_mp3(part1.turns, part2.turns, mp3_path)
    print(f"[INFO] MP3結合・保存完了: {mp3_path} ({duration_sec}秒)")

    description_lines = (
        [f"【本日のテーマ】{weekly_theme['label']}", "", "【第1部：経済ニュース】"]
        + [f"・{b}" for b in part1.summary_bullets]
        + ["", "【第2部：ビジネスニュース】"]
        + [f"・{b}" for b in part2.summary_bullets]
    )
    if part2.keyword_of_the_day:
        description_lines += ["", f"【今日の1ワード】{part2.keyword_of_the_day}"]

    meta = {
        "title": f"{date_label} | {part1.part_title} ほか",
        "description": "\n".join(description_lines),
        "duration_sec": duration_sec,
        "weekly_theme": weekly_theme["label"],
        "keyword_of_the_day": part2.keyword_of_the_day,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    cleanup_old_episodes()
    build_rss_feed()
    print("=== 処理が正常に完了しました ===")


if __name__ == "__main__":
    main()
