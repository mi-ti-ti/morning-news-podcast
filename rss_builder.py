"""古いエピソードの削除とPodcast用RSS（feed.xml）生成"""

import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
import xml.etree.ElementTree as ET

from pydub import AudioSegment

import config

JST = timezone(timedelta(hours=9))
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NS)


def cleanup_old_episodes(retention_days: int = config.RETENTION_DAYS) -> None:
    """最新の指定件数（日数分）を超えた古いMP3およびメタデータJSONを削除する"""
    if not config.EPISODES_DIR.exists():
        return
    mp3_files = sorted(config.EPISODES_DIR.glob("*.mp3"), reverse=True)
    for old_mp3 in mp3_files[retention_days:]:
        print(f"[INFO] 古いエピソードを削除: {old_mp3.name}")
        old_mp3.unlink(missing_ok=True)
        meta_file = old_mp3.with_suffix(".json")
        meta_file.unlink(missing_ok=True)


def _format_duration(seconds: int) -> str:
    mins, secs = divmod(max(seconds, 0), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def build_rss_feed() -> None:
    """docs/episodes/*.mp3 をもとに docs/feed.xml を再生成する"""
    base_url = config.get_base_url()
    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    config.EPISODES_DIR.mkdir(parents=True, exist_ok=True)

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = config.PODCAST_TITLE
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "description").text = config.PODCAST_DESCRIPTION
    ET.SubElement(channel, "language").text = config.PODCAST_LANGUAGE
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(JST))

    ET.SubElement(channel, f"{{{ITUNES_NS}}}author").text = config.PODCAST_AUTHOR
    ET.SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = "false"
    owner = ET.SubElement(channel, f"{{{ITUNES_NS}}}owner")
    ET.SubElement(owner, f"{{{ITUNES_NS}}}name").text = config.PODCAST_AUTHOR

    cover_path = config.DOCS_DIR / "cover.png"
    if cover_path.exists():
        ET.SubElement(channel, f"{{{ITUNES_NS}}}image", {"href": f"{base_url}/cover.png"})

    cat = ET.SubElement(channel, f"{{{ITUNES_NS}}}category", {"text": config.PODCAST_CATEGORY})
    ET.SubElement(cat, f"{{{ITUNES_NS}}}category", {"text": config.PODCAST_SUBCATEGORY})

    mp3_files = sorted(config.EPISODES_DIR.glob("*.mp3"), reverse=True)
    for mp3_path in mp3_files:
        date_stem = mp3_path.stem  # 例: 2026-11-18
        meta_path = mp3_path.with_suffix(".json")
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}

        try:
            pub_dt = datetime.strptime(date_stem, "%Y-%m-%d").replace(
                hour=5, minute=0, second=0, tzinfo=JST
            )
        except ValueError:
            pub_dt = datetime.fromtimestamp(mp3_path.stat().st_mtime, tz=JST)

        duration_sec = meta.get("duration_sec")
        if not duration_sec:
            audio = AudioSegment.from_mp3(mp3_path)
            duration_sec = int(round(len(audio) / 1000.0))

        title = meta.get("title") or f"{date_stem} の経済・ビジネスニュース"
        description = meta.get("description") or config.PODCAST_DESCRIPTION
        mp3_url = f"{base_url}/episodes/{mp3_path.name}"
        file_size = mp3_path.stat().st_size

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = description
        ET.SubElement(item, "pubDate").text = format_datetime(pub_dt)
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = f"podcast-{date_stem}"
        ET.SubElement(
            item,
            "enclosure",
            {"url": mp3_url, "length": str(file_size), "type": "audio/mpeg"},
        )
        ET.SubElement(item, f"{{{ITUNES_NS}}}duration").text = _format_duration(duration_sec)
        ET.SubElement(item, f"{{{ITUNES_NS}}}explicit").text = "false"

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    tree.write(config.FEED_XML_PATH, encoding="utf-8", xml_declaration=True)
    print(f"[INFO] RSSフィードを更新しました: {config.FEED_XML_PATH}")
