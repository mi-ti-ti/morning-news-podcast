"""VOICEVOX Core による音声合成と pydub による MP3 結合"""

import io
from pathlib import Path
from typing import List

from pydub import AudioSegment
from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile

import config
from script_generator import DialogueTurn


def _init_synthesizer() -> Synthesizer:
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
    synthesizer: Synthesizer,
    turns: List[DialogueTurn],
    speaker_map: dict,
) -> AudioSegment:
    """1パート分のDialogueTurnリストをVOICEVOX Coreで合成し、結合したAudioSegmentを返す"""
    combined = AudioSegment.empty()
    turn_pause = AudioSegment.silent(duration=250)  # 掛け合い間の自然な間（0.25秒）

    for idx, turn in enumerate(turns, start=1):
        text = turn.text.strip()
        if not text:
            continue
        sp_cfg = speaker_map.get(turn.speaker) or next(iter(speaker_map.values()))
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
            print(f"    ... {idx}/{len(turns)} ターン合成完了")

    return combined


def build_combined_mp3(
    part1_turns: List[DialogueTurn],
    part2_turns: List[DialogueTurn],
    output_mp3_path: Path,
) -> int:
    """第1部・第2部をそれぞれVOICEVOX Coreで合成し、pydubで結合してMP3保存する。再生秒数を返す。"""
    print("[INFO] VOICEVOX Core を初期化中...")
    synthesizer = _init_synthesizer()
    speaker_map = {sp["name"]: sp for sp in config.SPEAKERS}

    print("[INFO] 第1部（経済）の音声を合成中...")
    seg1 = _synthesize_part_segment(synthesizer, part1_turns, speaker_map)

    print("[INFO] 第2部（ビジネス）の音声を合成中...")
    seg2 = _synthesize_part_segment(synthesizer, part2_turns, speaker_map)

    part_pause = AudioSegment.silent(duration=800)  # パート間の間（0.8秒）
    combined = seg1 + part_pause + seg2

    output_mp3_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(output_mp3_path, format="mp3", bitrate="128k")

    duration_sec = int(round(len(combined) / 1000.0))
    return duration_sec
