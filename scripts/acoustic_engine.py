#!/usr/bin/env python3
"""
acoustic_engine.py — MomentCatcher FR-1

WAV ファイルから「熱量スパイク」を検出し、秒数と強度を JSON で出力する。

使い方:
    python scripts/acoustic_engine.py audio.wav > spikes.json
    python scripts/acoustic_engine.py audio.wav --output spikes.json

アルゴリズム:
    1. RMS（音量）を hop_length ごとに計算
    2. pYIN で F0（基本周波数）を推定し、各フレームの標準偏差をピッチ分散として算出
    3. heat_index = normalized_rms × (1 + normalized_pitch_var)
    4. 95パーセンタイル超のフレームをスパイク候補とする
    5. 0.5秒以内の隣接スパイクをマージ（最大強度のフレームを代表点にする）

出力 JSON:
    [{"seconds": 12.3, "intensity": 1.42}, ...]
    スパイクがない場合は空配列 [] を返す
"""

import argparse
import json
import sys
from pathlib import Path

import librosa
import numpy as np


# ─── 定数 ────────────────────────────────────────────────────────────────────

SR              = 22050   # サンプリングレート（librosa デフォルト）
HOP_LENGTH      = 512     # フレームシフト（約23ms）
SPIKE_PERCENTILE = 95     # このパーセンタイルを超えたフレームをスパイク候補とする
MERGE_SECONDS   = 0.5     # この秒数以内の隣接スパイクをマージする


# ─── メイン処理 ───────────────────────────────────────────────────────────────

def detect_spikes(wav_path: str) -> list[dict]:
    """WAV ファイルを解析してスパイクリストを返す。"""
    y, sr = librosa.load(wav_path, sr=SR, mono=True)

    # 1. RMS エネルギー
    rms = librosa.feature.rms(y=y, hop_length=HOP_LENGTH)[0]

    # 2. F0 推定（pYIN）
    f0, voiced_flag, _ = librosa.pyin(
        y,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C7"),
        sr=sr,
        hop_length=HOP_LENGTH,
    )
    # 無声区間を 0 に置換してピッチ分散を算出（窓幅: ±10フレーム = 約0.23秒）
    f0_safe = np.where(voiced_flag, f0, 0.0)
    window  = 10
    pitch_var = np.array([
        np.std(f0_safe[max(0, i - window): i + window])
        for i in range(len(f0_safe))
    ])

    # フレーム数を rms に揃える
    min_len   = min(len(rms), len(pitch_var))
    rms       = rms[:min_len]
    pitch_var = pitch_var[:min_len]

    # 3. heat_index の計算（0–1 正規化後に結合）
    rms_norm  = _normalize(rms)
    pvar_norm = _normalize(pitch_var)
    heat      = rms_norm * (1.0 + pvar_norm)

    # 4. スパイク候補フレームを抽出
    threshold     = np.percentile(heat, SPIKE_PERCENTILE)
    spike_frames  = np.where(heat > threshold)[0]

    if len(spike_frames) == 0:
        return []

    # フレーム → 秒数に変換
    spike_times = librosa.frames_to_time(spike_frames, sr=sr, hop_length=HOP_LENGTH)
    spike_heats = heat[spike_frames]

    # 5. 隣接スパイクをマージ
    merged = _merge_spikes(spike_times, spike_heats, merge_gap=MERGE_SECONDS)

    return merged


def _normalize(arr: np.ndarray) -> np.ndarray:
    """0–1 正規化。全値が同一の場合は 0 を返す。"""
    mn, mx = arr.min(), arr.max()
    if mx == mn:
        return np.zeros_like(arr, dtype=float)
    return (arr - mn) / (mx - mn)


def _merge_spikes(
    times: np.ndarray,
    heats: np.ndarray,
    merge_gap: float,
) -> list[dict]:
    """merge_gap 秒以内の隣接スパイクをマージし、最大強度の点を代表として返す。"""
    if len(times) == 0:
        return []

    groups: list[list[int]] = [[0]]
    for i in range(1, len(times)):
        if times[i] - times[groups[-1][-1]] <= merge_gap:
            groups[-1].append(i)
        else:
            groups.append([i])

    result = []
    for group in groups:
        best_idx = group[np.argmax(heats[group])]
        result.append({
            "seconds":   round(float(times[best_idx]), 2),
            "intensity": round(float(heats[best_idx]), 4),
        })
    return result


# ─── CLI エントリポイント ──────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Detect acoustic heat spikes from a WAV file."
    )
    p.add_argument("wav_file", help="Path to input WAV file")
    p.add_argument(
        "--output", "-o",
        help="Output JSON file path (default: stdout)",
        default=None,
    )
    return p.parse_args()


def main() -> None:
    args   = parse_args()
    spikes = detect_spikes(args.wav_file)

    output = json.dumps(spikes, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"スパイク検出完了: {len(spikes)} 件 → {args.output}", file=sys.stderr)
    else:
        print(output)
        print(f"スパイク検出完了: {len(spikes)} 件", file=sys.stderr)


if __name__ == "__main__":
    main()
