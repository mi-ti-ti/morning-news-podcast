"""番組設定・モデル設定・キャラクター設定（VOICEVOX Core 版）"""

import os
import sys
from pathlib import Path

# --- パス設定 ---
BASE_DIR = Path(__file__).resolve().parents[2]
DOCS_DIR = BASE_DIR / "docs"
EPISODES_DIR = DOCS_DIR / "episodes"
FEED_XML_PATH = DOCS_DIR / "feed.xml"
FEEDS_CONFIG_PATH = BASE_DIR / "feeds.yaml"

# --- VOICEVOX Core アセットパス ---
VOICEVOX_DIR = Path(os.getenv("VOICEVOX_DIR", BASE_DIR / "voicevox_assets"))
VOICEVOX_DICT_DIR = VOICEVOX_DIR / "open_jtalk_dic_utf_8-1.11"
VOICEVOX_VVM_PATH = VOICEVOX_DIR / "0.vvm"


def find_onnxruntime_path() -> Path:
    """実行OSに応じた ONNX Runtime 共有ライブラリを voicevox_assets 内から探索する"""
    env_path = os.getenv("VOICEVOX_ONNXRUNTIME_PATH", "").strip()
    if env_path:
        return Path(env_path)

    candidates = sorted(VOICEVOX_DIR.rglob("*voicevox_onnxruntime*"))
    if sys.platform == "darwin":
        for p in candidates:
            if p.is_file() and p.suffix == ".dylib":
                return p
        return VOICEVOX_DIR / "lib" / "libvoicevox_onnxruntime.1.17.3.dylib"

    if sys.platform == "win32":
        for p in candidates:
            if p.is_file() and p.suffix.lower() == ".dll":
                return p
        return VOICEVOX_DIR / "lib" / "voicevox_onnxruntime.dll"

    for p in candidates:
        if p.is_file() and ".so" in p.suffixes:
            return p
    return VOICEVOX_DIR / "lib" / "libvoicevox_onnxruntime.so.1.17.3"


# --- モデル設定 ---
SCRIPT_MODEL = "gemini-3.8-flash"

# --- 番組メタデータ ---
PODCAST_TITLE = "毎朝5時の経済・ビジネスニュース"
PODCAST_DESCRIPTION = (
    "毎朝5:00（JST）に最新の経済・ビジネスニュースを収集し、"
    "背景や仕組みまで深掘りしてずんだもんと春日部つむぎの掛け合いで明るくお届けする自動生成ポッドキャストです。\n"
    "音声：VOICEVOX:ずんだもん、VOICEVOX:春日部つむぎ"
)
PODCAST_AUTHOR = "Personal AI Podcast"
PODCAST_LANGUAGE = "ja"
PODCAST_CATEGORY = "Business"
PODCAST_SUBCATEGORY = "Business News"


def get_base_url() -> str:
    env_url = os.getenv("PODCAST_BASE_URL", "").strip().rstrip("/")
    if env_url:
        return env_url
    github_repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    if "/" in github_repo:
        owner, repo = github_repo.split("/", 1)
        return f"https://{owner}.github.io/{repo}"
    return "https://YOUR_USERNAME.github.io/YOUR_REPO_NAME"


# --- 保持期間・過去回連携・尺設定 ---
RETENTION_DAYS = 21  # 最新21日分のMP3を保持し、古いファイルを自動削除
CONTEXT_HISTORY_DAYS = 7  # 過去回連携（「点と線」）のために参照する直近日数
TARGET_CHARS_PER_PART = "1,500〜1,800文字"  # 各部約5分目安

# --- 曜日別テーマ設定（0=月曜 〜 6=日曜） ---
WEEKLY_THEMES = {
    0: {
        "label": "月曜・今週の注目イベント予習",
        "instruction": "週明けのため、今週予定されている重要経済指標・金融政策イベント・主要企業の決算や注目予定を優先して取り上げ、今週の見どころを予習する回にしてください。",
    },
    1: {
        "label": "火曜・最新トレンド深掘り",
        "instruction": "最新の経済・企業ニュースの中から、特に構造変化や市場へのインパクトが大きいトピックを厳選して深掘りしてください。",
    },
    2: {
        "label": "水曜・テック＆新ビジネスモデル特集",
        "instruction": "生成AI・半導体・DX・スタートアップ動向や、企業の新しいビジネスモデル・収益構造の工夫に注目したトピックを厚めに扱ってください。",
    },
    3: {
        "label": "木曜・マーケット＆産業動向深掘り",
        "instruction": "為替・金利・物価や主要産業（自動車・小売・金融・エネルギー等）の動きが生活や企業にどう波及するかを深掘りしてください。",
    },
    4: {
        "label": "金曜・今週の総括＆振り返り",
        "instruction": "直近数日のニュースを振り返りつつ、今週一番大きかった経済・ビジネスの流れを整理して週末につながるまとめ回にしてください。",
    },
    5: {
        "label": "土曜・業界構造＆企業戦略ケーススタディ",
        "instruction": "週末回として、話題の業界や注目企業の戦略・競争優位性を1つ取り上げ、ビジネスモデルがわかるケーススタディ調で丁寧に解説してください。",
    },
    6: {
        "label": "日曜・ニュースを読み解く経済の基礎教養",
        "instruction": "週末回として、最近のニュースの理解に直結する経済・金融の仕組み（例：金利と為替の関係、インフレのメカニズム等）をニュースと絡めて基礎から解説してください。",
    },
}

# --- パーソナリティ設定（VOICEVOX style_id） ---
# 0.vvm 収録話者: ずんだもん(ノーマル)=3, 春日部つむぎ(ノーマル)=8
SPEAKERS = [
    {
        "name": "ずんだもん",
        "style_id": 3,
        "speed_scale": 1.05,
        "role": "進行役・元気なメインパーソナリティ",
        "persona": (
            "明るく元気で好奇心旺盛な進行役。リスナーと同じ目線で「なんでそうなるのだ？」「僕たちの生活にどう関係あるのだ？」と素朴な疑問を投げる。"
            "語尾に「〜なのだ」「〜のだ」を自然に使ってテンポよく番組を回す。"
        ),
    },
    {
        "name": "春日部つむぎ",
        "style_id": 8,
        "speed_scale": 1.05,
        "role": "コメンテーター・わかりやすい解説役",
        "persona": (
            "親しみやすく頼れる解説役。一人称は「あーし」または「私」で、"
            "「〜だよね」「〜ってことなんだよ」など柔らかい話し言葉で、"
            "ニュースの背景にある経済メカニズムや企業戦略を身近な例にたとえてわかりやすく解説する。"
        ),
    },
]
