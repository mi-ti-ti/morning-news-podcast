"""VOICEVOX Core による音声合成と pydub による MP3 結合"""

import io
from pathlib import Path

from pydub import AudioSegment

from . import config
from .schema import DialogueTurn, MAX_CHARS_PER_TURN, MAX_TURNS_PER_PART
from .voicevox_setup import ensure_voicevox_assets

PART_PAUSE_MS = 800


def _init_synthesizer():
    from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile

    ensure_voicevox_assets()
    onnxruntime_path = config.find_onnxruntime_path()
    if not onnxruntime_path.exists():
        raise FileNotFoundError(
            f"VOICEVOX ONNX Runtime が見つかりません: {onnxruntime_path}"
        )
    if not config.VOICEVOX_DICT_DIR.exists():
        raise FileNotFoundError(
            f"OpenJTalk 辞書が見つかりません: {config.VOICEVOX_DICT_DIR}"
        )
    if not config.VOICEVOX_VVM_PATH.exists():
        raise FileNotFoundError(
            f"VOICEVOX 音声モデル (0.vvm) が見つかりません: {config.VOICEVOX_VVM_PATH}"
        )

    ort = Onnxruntime.load_once(filename=str(onnxruntime_path))
    openjtalk = OpenJtalk(str(config.VOICEVOX_DICT_DIR))
    synthesizer = Synthesizer(ort, openjtalk)

    with VoiceModelFile.open(str(config.VOICEVOX_VVM_PATH)) as model:
        synthesizer.load_voice_model(model)

    return synthesizer


def _synthesize_part_segment(
    synthesizer,
    turns: list[DialogueTurn],
    speaker_map: dict,
) -> AudioSegment:
    """1パート分のDialogueTurnリストをVOICEVOX Coreで合成し、結合したAudioSegmentを返す"""
    combined = AudioSegment.empty()
    turn_pause = AudioSegment.silent(duration=250)  # 掛け合い間の自然な間（0.25秒）

    turns_to_synthesize = turns[:MAX_TURNS_PER_PART]
    for idx, turn in enumerate(turns_to_synthesize, start=1):
        text = turn.text.strip()[:MAX_CHARS_PER_TURN]
        if not text:
            continue
        if turn.speaker not in speaker_map:
            raise ValueError(f"未定義の話者名です: {turn.speaker!r}")
        sp_cfg = speaker_map[turn.speaker]
        style_id = sp_cfg["style_id"]
        speed_scale = sp_cfg.get("speed_scale", 1.0)

        audio_query = synthesizer.create_audio_query(text, style_id)
        audio_query.speed_scale = speed_scale
        wav_bytes = synthesizer.synthesis(audio_query, style_id)

        seg = AudioSegment.from_wav(io.BytesIO(wav_bytes))
        if len(combined) > 0:
            combined += turn_pause
        combined += seg

        if idx % 10 == 0:
            print(f"    ... {idx}/{len(turns_to_synthesize)} ターン合成完了")

    return combined


def build_episode_mp3(
    parts: list[list[DialogueTurn]],
    output_mp3_path: Path,
) -> int:
    """1つ以上のパートをVOICEVOX Coreで合成し、パート間に無音を挟んでMP3保存する。再生秒数を返す。"""
    if not parts:
        raise ValueError("音声合成対象のパートが1つも指定されていません")

    print("[INFO] VOICEVOX Core を初期化中...")
    synthesizer = _init_synthesizer()
    speaker_map = {sp["name"]: sp for sp in config.SPEAKERS}

    part_pause = AudioSegment.silent(duration=PART_PAUSE_MS)
    combined = AudioSegment.empty()

    total_parts = len(parts)
    for idx, turns in enumerate(parts, start=1):
        print(f"[INFO] パート {idx}/{total_parts} の音声を合成中...")
        seg = _synthesize_part_segment(synthesizer, turns, speaker_map)
        if len(combined) > 0 and len(seg) > 0:
            combined += part_pause
        combined += seg

    output_mp3_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(output_mp3_path, format="mp3", bitrate="128k")

    duration_sec = int(round(len(combined) / 1000.0))
    return duration_sec
