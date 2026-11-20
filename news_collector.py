"""RSSフィード取得・過去エピソード参照・Gemini Google検索グラウンディング"""

import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Tuple

import feedparser
import yaml
from google import genai
from google.genai import types

import config

JST = timezone(timedelta(hours=9))


def load_feeds_config() -> Dict[str, List[dict]]:
    with open(config.FEEDS_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_recent_episode_context(
    days: int = config.CONTEXT_HISTORY_DAYS,
) -> Tuple[str, List[str]]:
    """直近の過去エピソードJSONから要約と既出キーワードを読み込む"""
    if not config.EPISODES_DIR.exists():
        return "（過去の配信履歴なし）", []

    today_stem = datetime.now(JST).strftime("%Y-%m-%d")
    json_files = sorted(config.EPISODES_DIR.glob("*.json"), reverse=True)

    history_lines: List[str] = []
    used_keywords: List[str] = []

    for jf in json_files:
        if jf.stem == today_stem:
            continue
        if len(history_lines) >= days:
            break
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            title = data.get("title", jf.stem)
            desc = (data.get("description") or "").replace("\n", " ")[:220]
            history_lines.append(f"- [{jf.stem}] {title}: {desc}")
            kw = data.get("keyword_of_the_day")
            if kw:
                used_keywords.append(kw)
        except Exception:
            continue

    history_text = "\n".join(history_lines) if history_lines else "（過去の配信履歴なし）"
    return history_text, used_keywords


def _parse_published(entry: dict) -> datetime | None:
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(JST)
            except Exception:
                pass
    if entry.get("published_parsed"):
        try:
            return datetime(*entry["published_parsed"][:6], tzinfo=timezone.utc).astimezone(JST)
        except Exception:
            pass
    return None


def fetch_rss_articles(feeds: List[dict], hours_back: int = 48, max_per_feed: int = 8) -> str:
    cutoff = datetime.now(JST) - timedelta(hours=hours_back)
    lines: List[str] = []

    for feed_info in feeds:
        name = feed_info.get("name", "Unknown")
        url = feed_info.get("url", "")
        if not url:
            continue
        try:
            parsed = feedparser.parse(
                url,
                request_headers={"User-Agent": "MorningNewsPodcastBot/1.0"},
            )
            if parsed.bozo and not parsed.entries:
                print(f"[WARN] RSS取得スキップ ({name}): {parsed.bozo_exception}")
                continue

            count = 0
            for entry in parsed.entries:
                if count >= max_per_feed:
                    break
                pub_dt = _parse_published(entry)
                if pub_dt and pub_dt < cutoff:
                    continue
                title = (entry.get("title") or "").strip()
                summary = (entry.get("summary") or entry.get("description") or "").strip()
                if summary:
                    summary = summary.replace("\n", " ")[:200]
                if title:
                    lines.append(f"- [{name}] {title} ({summary})")
                    count += 1
        except Exception as exc:
            print(f"[WARN] RSS取得エラー ({name}): {exc}")

    return "\n".join(lines) if lines else "（RSS記事の取得結果なし）"


def gather_news_briefing(
    client: genai.Client,
    category_label: str,
    rss_text: str,
    weekly_theme: dict,
    past_context: str,
) -> str:
    """RSS記事・過去履歴・Google検索グラウンディングを組み合わせて深掘り資料を作成する"""
    today_str = datetime.now(JST).strftime("%Y年%m月%d日")
    prompt = f"""あなたは経済・ビジネスに精通した敏腕リサーチャーです。
今日の日付は {today_str} です。

【本日の曜日テーマ：{weekly_theme['label']}】
{weekly_theme['instruction']}

以下のRSS記事リスト・過去の配信履歴・Google検索ツールによる最新情報（過去24時間のトレンド）をもとに、
本日の{category_label}パートで深く解説すべきトピックを **1〜2件だけ厳選** し、聴き手の知見が深まる構成資料を作成してください。

【過去の配信履歴（点と線をつなぐ参考情報）】
{past_context}

【RSS取得記事】
{rss_text}

【出力要件（3ステップ深掘り構成）】
トピック数を1〜2件に絞る代わりに、各トピックについて以下4点を具体的な事実・数値とともに整理すること：
1. **何が起きたか（事実）**: 最新の数値、企業名、発表内容。
2. **なぜ起きたか（背景・経済メカニズム）**: 歴史的経緯、業界の構造、需給や金融政策の仕組みなど「なぜそうなるのか」の解説。
3. **過去とのつながり（該当する場合のみ）**: 過去の配信履歴に関連トピックや続報があれば「前回の〇〇の続きとしてどう動いたか」を明記。
4. **私たちの生活・仕事・投資への影響**: 一般のビジネスパーソンや生活者にとって何がどう変わるのかの視点。

※ 推測や未確認の情報は書かないこと。
"""

    response = client.models.generate_content(
        model=config.SCRIPT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.3,
        ),
    )
    return response.text or rss_text


def collect_all_news(
    client: genai.Client,
    weekly_theme: dict,
) -> Dict[str, object]:
    feeds_cfg = load_feeds_config()
    econ_rss = fetch_rss_articles(feeds_cfg.get("economy", []))
    biz_rss = fetch_rss_articles(feeds_cfg.get("business", []))
    past_context, used_keywords = load_recent_episode_context()

    print(f"[INFO] 本日のテーマ: {weekly_theme['label']}")
    print("[INFO] 第1部（経済ニュース）を深掘り調査・整理中...")
    econ_briefing = gather_news_briefing(
        client, "経済・金融・マーケット", econ_rss, weekly_theme, past_context
    )

    print("[INFO] 第2部（ビジネスニュース）を深掘り調査・整理中...")
    biz_briefing = gather_news_briefing(
        client, "ビジネス・企業動向・テクノロジー", biz_rss, weekly_theme, past_context
    )

    return {
        "economy": econ_briefing,
        "business": biz_briefing,
        "past_context": past_context,
        "used_keywords": used_keywords,
    }
