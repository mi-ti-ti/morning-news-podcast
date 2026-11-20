"""実行環境（OS / CPUアーキテクチャ）に応じた VOICEVOX Core アセットの自動セットアップ"""

import platform
import posixpath
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from . import config

OPEN_JTALK_DICT_URL = (
    "https://github.com/r9y9/open_jtalk/releases/download/v1.11.1/open_jtalk_dic_utf_8-1.11.tar.gz"
)
VOICE_MODEL_URL = (
    f"https://github.com/VOICEVOX/voicevox_vvm/releases/download/{config.VOICEVOX_CORE_VERSION}/0.vvm"
)

_ONNXRUNTIME_TARGETS: dict[tuple[str, str], str] = {
    ("linux", "x86_64"): f"voicevox_onnxruntime-linux-x64-{config.ONNXRUNTIME_VERSION}.tgz",
    ("linux", "amd64"): f"voicevox_onnxruntime-linux-x64-{config.ONNXRUNTIME_VERSION}.tgz",
    ("linux", "aarch64"): f"voicevox_onnxruntime-linux-arm64-{config.ONNXRUNTIME_VERSION}.tgz",
    ("linux", "arm64"): f"voicevox_onnxruntime-linux-arm64-{config.ONNXRUNTIME_VERSION}.tgz",
    ("darwin", "arm64"): f"voicevox_onnxruntime-osx-arm64-{config.ONNXRUNTIME_VERSION}.tgz",
    ("darwin", "x86_64"): f"voicevox_onnxruntime-osx-x86_64-{config.ONNXRUNTIME_VERSION}.tgz",
    ("win32", "amd64"): f"voicevox_onnxruntime-win-x64-{config.ONNXRUNTIME_VERSION}.tgz",
    ("win32", "x86_64"): f"voicevox_onnxruntime-win-x64-{config.ONNXRUNTIME_VERSION}.tgz",
}


def get_onnxruntime_url() -> str:
    """現在の OS・アーキテクチャに対応する VOICEVOX ONNX Runtime アーカイブ URL を返す"""
    os_name = sys.platform
    arch = platform.machine().lower()
    asset_name = _ONNXRUNTIME_TARGETS.get((os_name, arch))
    if not asset_name:
        raise RuntimeError(
            f"未対応のプラットフォームです: platform={os_name}, machine={arch}。"
            "DOCKER または手動で VOICEVOX_ONNXRUNTIME_PATH を指定してください。"
        )
    return (
        f"https://github.com/VOICEVOX/onnxruntime-builder/releases/download/"
        f"voicevox_onnxruntime-{config.ONNXRUNTIME_VERSION}/{asset_name}"
    )


def _download_file(url: str, dest_path: Path) -> None:
    """URL からファイルをダウンロードし、一時ファイル経由で安全に保存する"""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
    req = urllib.request.Request(url, headers={"User-Agent": "MorningNewsPodcastSetup/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp_path, "wb") as f:
            while chunk := resp.read(1024 * 64):
                f.write(chunk)
        tmp_path.replace(dest_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _strip_archive_path(raw_path: str, strip_components: int) -> str | None:
    normalized = posixpath.normpath(raw_path.lstrip("/"))
    if normalized in ("", "."):
        return None
    parts = [p for p in normalized.split("/") if p and p != "."]
    if len(parts) <= strip_components:
        return None
    stripped = parts[strip_components:]
    if ".." in stripped:
        raise ValueError(f"不正なアーカイブパスが検出されました: {raw_path}")
    return "/".join(stripped)


def _extract_targz(archive_path: Path, dest_dir: Path, strip_components: int = 0) -> None:
    """tar.gz / tgz アーカイブを安全に展開する（パストラバーサル対策付き）"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_root = dest_dir.resolve()

    with tarfile.open(archive_path, "r:gz") as tar:
        members: list[tarfile.TarInfo] = []
        for member in tar.getmembers():
            new_name = _strip_archive_path(member.name, strip_components)
            if not new_name:
                continue
            target_path = (dest_root / new_name).resolve()
            if not target_path.is_relative_to(dest_root):
                raise ValueError(f"展開先ディレクトリ外へのパスが検出されました: {member.name}")

            member.name = new_name
            if member.islnk() and strip_components > 0:
                stripped_link = _strip_archive_path(member.linkname, strip_components)
                if not stripped_link:
                    continue
                member.linkname = stripped_link
            members.append(member)

        tar.extractall(path=dest_dir, members=members, filter="data")


def ensure_voicevox_assets() -> None:
    """不足している VOICEVOX Core アセット（ONNX Runtime / 辞書 / 0.vvm）を自動取得する"""
    config.VOICEVOX_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)

        if not config.find_onnxruntime_path().exists():
            ort_url = get_onnxruntime_url()
            print(f"[INFO] VOICEVOX ONNX Runtime をダウンロード中: {ort_url}")
            ort_archive = tmp_dir / "ort.tgz"
            _download_file(ort_url, ort_archive)
            _extract_targz(ort_archive, config.VOICEVOX_DIR, strip_components=1)
            print(f"[INFO] VOICEVOX ONNX Runtime の配置完了: {config.find_onnxruntime_path()}")

        if not config.VOICEVOX_DICT_DIR.exists():
            print(f"[INFO] OpenJTalk 辞書をダウンロード中: {OPEN_JTALK_DICT_URL}")
            dict_archive = tmp_dir / "open_jtalk_dic.tar.gz"
            _download_file(OPEN_JTALK_DICT_URL, dict_archive)
            _extract_targz(dict_archive, config.VOICEVOX_DIR, strip_components=0)
            print(f"[INFO] OpenJTalk 辞書の配置完了: {config.VOICEVOX_DICT_DIR}")

    if not config.VOICEVOX_VVM_PATH.exists():
        print(f"[INFO] VOICEVOX 音声モデル (0.vvm) をダウンロード中: {VOICE_MODEL_URL}")
        _download_file(VOICE_MODEL_URL, config.VOICEVOX_VVM_PATH)
        print(f"[INFO] VOICEVOX 音声モデルの配置完了: {config.VOICEVOX_VVM_PATH}")


if __name__ == "__main__":
    ensure_voicevox_assets()
