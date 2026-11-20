"""Unit tests for news_collector.py"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from morning_news_podcast import config, news_collector


class TestNewsCollector(unittest.TestCase):
    def test_gather_daily_briefings_delimiter_splitting_single_call(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = SimpleNamespace(
            text=(
                f"{news_collector.PART1_DELIMITER}\n"
                "第1部の経済ニュース深掘り内容\n\n"
                f"{news_collector.PART2_DELIMITER}\n"
                "第2部のビジネスニュース深掘り内容\n"
            )
        )

        weekly_theme = config.WEEKLY_THEMES[1]
        econ, biz = news_collector.gather_daily_briefings(
            mock_client,
            "- [日経] 経済RSS",
            "- [TechCrunch] ビジネスRSS",
            weekly_theme,
            "（過去の配信履歴なし）",
        )

        self.assertEqual(mock_client.models.generate_content.call_count, 1)
        self.assertEqual(econ, "第1部の経済ニュース深掘り内容")
        self.assertEqual(biz, "第2部のビジネスニュース深掘り内容")

    def test_gather_daily_briefings_fallback_when_delimiters_missing(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = SimpleNamespace(
            text="デリミタなしの統合レスポンス全文"
        )

        econ, biz = news_collector.gather_daily_briefings(
            mock_client,
            "econ-rss",
            "biz-rss",
            config.WEEKLY_THEMES[0],
            "past",
        )

        self.assertEqual(econ, "デリミタなしの統合レスポンス全文")
        self.assertEqual(biz, "デリミタなしの統合レスポンス全文")

    def test_load_recent_episode_context_sorting_exclusion_and_window(self):
        now_jst = datetime.now(news_collector.JST)
        today_str = now_jst.strftime("%Y-%m-%d")
        yesterday = now_jst - timedelta(days=1)
        two_days_ago = now_jst - timedelta(days=2)
        ten_days_ago = now_jst - timedelta(days=10)

        with tempfile.TemporaryDirectory() as tmpdir:
            ep_dir = Path(tmpdir)
            # Today's daily episode (must be skipped)
            (ep_dir / f"{today_str}.json").write_text(
                json.dumps(
                    {
                        "title": "今日の通常回",
                        "description": "今日",
                        "keyword_of_the_day": "今日ワード",
                        "published_at": now_jst.replace(hour=5, minute=0).isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            # Yesterday's extra episode (included, sorted newest)
            y_str = yesterday.strftime("%Y-%m-%d")
            (ep_dir / f"{y_str}_extra-topic.json").write_text(
                json.dumps(
                    {
                        "title": "昨日の号外",
                        "description": "号外説明",
                        "keyword_of_the_day": "号外ワード",
                        "published_at": yesterday.replace(hour=18, minute=0).isoformat(),
                        "exclude_from_context": False,
                    }
                ),
                encoding="utf-8",
            )
            # Yesterday's daily episode without published_at (fallback to 05:00 JST)
            (ep_dir / f"{y_str}.json").write_text(
                json.dumps(
                    {
                        "title": "昨日の通常回",
                        "description": "通常説明",
                        "keyword_of_the_day": "通常ワード",
                    }
                ),
                encoding="utf-8",
            )
            # Excluded extra episode (must be skipped including keyword)
            (ep_dir / f"{y_str}_extra-excluded.json").write_text(
                json.dumps(
                    {
                        "title": "除外対象回",
                        "description": "除外",
                        "keyword_of_the_day": "除外ワード",
                        "published_at": yesterday.replace(hour=20, minute=0).isoformat(),
                        "exclude_from_context": True,
                    }
                ),
                encoding="utf-8",
            )
            # 2 days ago episode (included)
            d2_str = two_days_ago.strftime("%Y-%m-%d")
            (ep_dir / f"{d2_str}.json").write_text(
                json.dumps(
                    {
                        "title": "2日前の通常回",
                        "description": "2日前説明",
                        "keyword_of_the_day": "2日前ワード",
                    }
                ),
                encoding="utf-8",
            )
            # 10 days ago episode (outside 7-day window -> skipped)
            d10_str = ten_days_ago.strftime("%Y-%m-%d")
            (ep_dir / f"{d10_str}.json").write_text(
                json.dumps(
                    {
                        "title": "10日前の通常回",
                        "description": "古い説明",
                        "keyword_of_the_day": "古いワード",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(config, "EPISODES_DIR", ep_dir):
                history_text, used_keywords = news_collector.load_recent_episode_context(days=7)

        lines = history_text.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn(f"[{y_str}_extra-topic]", lines[0])
        self.assertIn(f"[{y_str}]", lines[1])
        self.assertIn(f"[{d2_str}]", lines[2])
        self.assertNotIn("今日の通常回", history_text)
        self.assertNotIn("除外対象回", history_text)
        self.assertNotIn("10日前の通常回", history_text)
        self.assertEqual(used_keywords, ["号外ワード", "通常ワード", "2日前ワード"])

    def test_fetch_rss_articles_summary_350_chars(self):
        long_summary = "あ" * 400
        rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Test Feed</title>
            <item>
              <title>テスト記事タイトル</title>
              <description>{long_summary}</description>
            </item>
          </channel>
        </rss>""".encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = rss_xml
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = news_collector.fetch_rss_articles(
                [{"name": "テスト紙", "url": "https://example.com/rss.xml"}]
            )

        self.assertIn("あ" * 350, result)
        self.assertNotIn("あ" * 351, result)


    def test_parse_daily_briefings_edge_cases(self):
        # Reversed delimiters -> fallback to full response text
        reversed_text = (
            f"{news_collector.PART2_DELIMITER}\nビジネス側\n"
            f"{news_collector.PART1_DELIMITER}\n経済側"
        )
        econ, biz = news_collector._parse_daily_briefings(
            reversed_text, "econ-rss", "biz-rss"
        )
        self.assertEqual(econ, reversed_text)
        self.assertEqual(biz, reversed_text)

        # Single delimiter only -> fallback to full response text
        single_delim = f"{news_collector.PART1_DELIMITER}\n経済だけ"
        econ, biz = news_collector._parse_daily_briefings(
            single_delim, "econ-rss", "biz-rss"
        )
        self.assertEqual(econ, single_delim)
        self.assertEqual(biz, single_delim)

        # Empty or None response -> fallback to econ_rss / biz_rss
        for empty_val in ("", "   \n", None):
            with self.subTest(empty_val=empty_val):
                econ, biz = news_collector._parse_daily_briefings(
                    empty_val, "econ-rss", "biz-rss"
                )
                self.assertEqual(econ, "econ-rss")
                self.assertEqual(biz, "biz-rss")


if __name__ == "__main__":
    unittest.main()
