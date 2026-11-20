"""古いエピソードの削除とPodcast用RSS（feed.xml）生成"""

import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
import xml.etree.ElementTree as ET

from pydub import AudioSegment

import config
from schema import strip_xml_control_chars

JST = timezone(timedelta(hours=9))
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NS)
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _load_meta(mp3_path: Path) -> dict:
    meta_path = mp3_path.with_suffix(".json")
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _resolve_published_at(mp3_path: Path, meta: dict) -> datetime:
    """メタデータの published_at を優先し、未設定時はファイル名先頭YYYY-MM-DD→05:00 JST にフォールバックする"""
    raw_pub = meta.get("published_at")
    if isinstance(raw_pub, str) and raw_pub.strip():
        try:
            dt = datetime.fromisoformat(raw_pub.strip())
            if dt.tzinfo is None or dt.utcoffset() is None:
                dt = dt.replace(tzinfo=JST)
            return dt.astimezone(JST)
        except ValueError:
            pass

    m = _DATE_PREFIX_RE.match(mp3_path.stem)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").replace(
                hour=5, minute=0, second=0, tzinfo=JST
            )
        except ValueError:
            pass

    return datetime.fromtimestamp(mp3_path.stat().st_mtime, tz=JST)


def cleanup_old_episodes(retention_days: int = config.RETENTION_DAYS) -> None:
    """保持期間（JST日付ベース）を超えた古いMP3およびメタデータJSONを削除する"""
    if not config.EPISODES_DIR.exists():
        return

    cutoff_date = datetime.now(JST).date() - timedelta(days=retention_days)
    for mp3_path in sorted(config.EPISODES_DIR.glob("*.mp3")):
        meta = _load_meta(mp3_path)
        pub_dt = _resolve_published_at(mp3_path, meta)
        if pub_dt.date() < cutoff_date:
            print(f"[INFO] 古いエピソードを削除: {mp3_path.name} (published_at={pub_dt.date()})")
            mp3_path.unlink(missing_ok=True)
            mp3_path.with_suffix(".json").unlink(missing_ok=True)


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

    ET.SubElement(channel, "title").text = strip_xml_control_chars(config.PODCAST_TITLE)
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "description").text = strip_xml_control_chars(config.PODCAST_DESCRIPTION)
    ET.SubElement(channel, "language").text = config.PODCAST_LANGUAGE
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(JST))

    ET.SubElement(channel, f"{{{ITUNES_NS}}}author").text = strip_xml_control_chars(config.PODCAST_AUTHOR)
    ET.SubElement(channel, f"{{{ITUNES_NS}}}explicit").text = "false"
    owner = ET.SubElement(channel, f"{{{ITUNES_NS}}}owner")
    ET.SubElement(owner, f"{{{ITUNES_NS}}}name").text = strip_xml_control_chars(config.PODCAST_AUTHOR)

    cover_path = config.DOCS_DIR / "cover.png"
    if cover_path.exists():
        ET.SubElement(channel, f"{{{ITUNES_NS}}}image", {"href": f"{base_url}/cover.png"})

    cat = ET.SubElement(channel, f"{{{ITUNES_NS}}}category", {"text": config.PODCAST_CATEGORY})
    ET.SubElement(cat, f"{{{ITUNES_NS}}}category", {"text": config.PODCAST_SUBCATEGORY})

    episodes: list[tuple[datetime, Path, dict]] = []
    for mp3_path in config.EPISODES_DIR.glob("*.mp3"):
        meta = _load_meta(mp3_path)
        pub_dt = _resolve_published_at(mp3_path, meta)
        episodes.append((pub_dt, mp3_path, meta))

    episodes.sort(key=lambda item: (item[0], item[1].stem), reverse=True)

    for pub_dt, mp3_path, meta in episodes:
        episode_id = mp3_path.stem  # 例: 2026-11-18 / 2026-11-20_extra-boj-rate
        duration_sec = meta.get("duration_sec")
        if not duration_sec:
            audio = AudioSegment.from_mp3(mp3_path)
            duration_sec = int(round(len(audio) / 1000.0))

        title = strip_xml_control_chars(
            str(meta.get("title") or f"{episode_id} の経済・ビジネスニュース")
        )
        description = strip_xml_control_chars(
            str(meta.get("description") or config.PODCAST_DESCRIPTION)
        )
        mp3_url = f"{base_url}/episodes/{mp3_path.name}"
        file_size = mp3_path.stat().st_size

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = description
        ET.SubElement(item, "pubDate").text = format_datetime(pub_dt)
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = f"podcast-{episode_id}"
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
