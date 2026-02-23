#!/usr/bin/env python3
"""
analyze.py — MomentCatcher FR-0 / FR-1

使い方:
    # FR-0（文字起こしのみ）
    python scripts/analyze.py transcripts/2026-02-23_Meeting.txt
    python scripts/analyze.py --mode fr0 transcripts/2026-02-23_Meeting.txt

    # FR-1（文字起こし + 音声スパイク）
    python scripts/analyze.py --mode fr1 --spikes spikes.json transcripts/2026-02-23_Meeting.txt

環境変数（GitHub Actions Secrets）:
    ANTHROPIC_API_KEY   Anthropic API キー
    SLACK_WEBHOOK_URL   Slack Incoming Webhook URL
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import requests

# ─── 定数 ────────────────────────────────────────────────────────────────────

PROMPT_PATH_FR0  = Path(__file__).parent.parent / "prompts" / "moment_catcher_skill.md"
PROMPT_PATH_FR1  = Path(__file__).parent.parent / "prompts" / "moment_catcher_skill_fr1.md"
MODEL            = "claude-sonnet-4-6"
MAX_TOKENS       = 2048

# 文字起こしが長すぎる場合のトークン対策（先頭から指定文字数を使用）
MAX_TRANSCRIPT_CHARS = 15_000


# ─── プロンプト読み込み ────────────────────────────────────────────────────────

def load_prompt_fr0(transcript_text: str, file_name: str) -> str:
    raw = PROMPT_PATH_FR0.read_text(encoding="utf-8")
    prompt = raw.replace("{transcript_text}", transcript_text)
    prompt = prompt.replace("{file_name}", file_name)
    return prompt


def load_prompt_fr1(transcript_text: str, spikes: list, file_name: str) -> str:
    raw = PROMPT_PATH_FR1.read_text(encoding="utf-8")
    spikes_str = json.dumps(spikes, ensure_ascii=False)
    prompt = raw.replace("{transcript_text}", transcript_text)
    prompt = prompt.replace("{file_name}", file_name)
    prompt = prompt.replace("{audio_spike_times}", spikes_str)
    return prompt


# ─── Claude API 呼び出し ───────────────────────────────────────────────────────

def analyze_transcript(prompt: str) -> dict:
    client  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    message = client.messages.create(
        model      = MODEL,
        max_tokens = MAX_TOKENS,
        messages   = [{"role": "user", "content": prompt}],
    )

    # レスポンスから JSON を抽出
    raw_text = message.content[0].text
    json_match = re.search(r"```json\s*(.*?)\s*```", raw_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))

    # コードブロックなしで JSON が返ってきた場合
    return json.loads(raw_text)


# ─── Slack 通知 ───────────────────────────────────────────────────────────────

def build_slack_message(result: dict, file_path: str, mode: str = "fr0") -> dict:
    file_name = Path(file_path).name
    date_str  = datetime.now().strftime("%Y-%m-%d %H:%M")
    mode_label = "FR-1 (音声スパイク付)" if mode == "fr1" else "FR-0"

    if result.get("no_moment_found"):
        return {
            "text": f":mag: *MomentCatcher* — 称賛の瞬間は見つかりませんでした",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f":mag: *MomentCatcher [{mode_label}]* — 称賛の瞬間が見つかりませんでした\n"
                            f"*会議ファイル*: `{file_name}`\n"
                            f"*解析日時*: {date_str}\n"
                            f"*会議概要*: {result.get('meeting_summary', '—')}"
                        ),
                    },
                }
            ],
        }

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":tada: MomentCatcher [{mode_label}] — Unipos 投稿ドラフトを生成しました",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*会議ファイル*\n`{file_name}`"},
                {"type": "mrkdwn", "text": f"*解析日時*\n{date_str}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*会議概要*\n{result.get('meeting_summary', '—')}",
            },
        },
        {"type": "divider"},
    ]

    for draft in result.get("drafts", []):
        rank      = draft.get("rank", "?")
        moment    = draft.get("moment", "")
        recipient = draft.get("recipient", "?")
        text      = draft.get("draft", "")
        reason    = draft.get("reason", "")

        # FR-1: 利用したスパイク情報を付加
        spikes_info = ""
        if mode == "fr1" and draft.get("spikes_utilized"):
            spike_strs = [
                f"{s['seconds']}秒 (強度: {s['intensity']:.2f})"
                for s in draft["spikes_utilized"]
            ]
            spikes_info = f"\n:sound: *利用スパイク*: {', '.join(spike_strs)}"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*【ドラフト {rank}】{moment}*\n"
                    f":bust_in_silhouette: 称賛相手: *{recipient}*"
                    f"{spikes_info}\n\n"
                    f"```{text}```\n"
                    f"_{reason}_"
                ),
            },
        })
        blocks.append({"type": "divider"})

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                ":pencil2: *内容を確認・編集して、Unipos に投稿してください。*\n"
                "ドラフトは自動生成です。あなた自身の言葉を添えて送ると、より伝わります。"
            ),
        },
    })

    return {"text": f"MomentCatcher [{mode_label}]: Unipos 投稿ドラフトを生成しました", "blocks": blocks}


def send_to_slack(message: dict) -> None:
    webhook_url = os.environ["SLACK_WEBHOOK_URL"]
    resp = requests.post(
        webhook_url,
        json=message,
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    print(f"Slack 送信完了: {resp.status_code}")


# ─── CLI パース ────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="MomentCatcher: analyze meeting transcript and post Unipos draft to Slack."
    )
    p.add_argument("transcript_file", help="Path to transcript text file")
    p.add_argument(
        "--mode", choices=["fr0", "fr1"], default="fr0",
        help="Analysis mode: fr0 (text only) or fr1 (text + audio spikes). Default: fr0",
    )
    p.add_argument(
        "--spikes", metavar="SPIKES_JSON",
        help="Path to spikes JSON file (required for --mode fr1)",
        default=None,
    )
    return p.parse_args()


# ─── エントリポイント ──────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    file_path       = args.transcript_file
    transcript_text = Path(file_path).read_text(encoding="utf-8")
    file_name       = Path(file_path).name

    print(f"解析開始 [{args.mode}]: {file_name} ({len(transcript_text)} 文字)")

    if args.mode == "fr1":
        if not args.spikes:
            print("--mode fr1 には --spikes <json_file> が必要です。", file=sys.stderr)
            sys.exit(1)
        spikes = json.loads(Path(args.spikes).read_text(encoding="utf-8"))
        print(f"スパイク数: {len(spikes)}")
        prompt = load_prompt_fr1(transcript_text[:MAX_TRANSCRIPT_CHARS], spikes, file_name)
    else:
        prompt = load_prompt_fr0(transcript_text[:MAX_TRANSCRIPT_CHARS], file_name)

    result = analyze_transcript(prompt)
    print("Claude 解析完了:", json.dumps(result, ensure_ascii=False, indent=2))

    message = build_slack_message(result, file_path, mode=args.mode)
    send_to_slack(message)


if __name__ == "__main__":
    main()
