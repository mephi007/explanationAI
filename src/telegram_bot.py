"""
telegram_bot.py — Preview bot for morning content review.
Sends all generated content to your Telegram at 6 AM IST.
Approve → pipeline posts. Regen → regenerates that piece. Skip → marks day skipped.

Setup: Create bot via @BotFather → get BOT_TOKEN.
       Start a chat with your bot → /start → get your CHAT_ID.
       Add both as GitHub Secrets.
"""

import os
import json
import time
import requests
from pathlib import Path
import db

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

AUTO_APPROVE_MINUTES = 30  # Auto-approve if no response in 30 min


def _send(method: str, **kwargs) -> dict:
    """Call Telegram Bot API."""
    resp = requests.post(f"{BASE_URL}/{method}", **kwargs)
    resp.raise_for_status()
    return resp.json()


def send_text(text: str, parse_mode: str | None = "Markdown") -> int:
    """Send text message, return message_id."""
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    result = _send("sendMessage", json=payload)
    return result["result"]["message_id"]


def send_video(video_path: str, caption: str = "") -> int:
    """Send video file."""
    with open(video_path, "rb") as f:
        result = _send("sendVideo", data={
            "chat_id": CHAT_ID,
            "caption": caption[:1024],
            "parse_mode": "Markdown",
        }, files={"video": f})
    return result["result"]["message_id"]


def send_document(doc_path: str, caption: str = "") -> int:
    """Send document (PDF carousel)."""
    with open(doc_path, "rb") as f:
        result = _send("sendDocument", data={
            "chat_id": CHAT_ID,
            "caption": caption[:1024],
            "parse_mode": "Markdown",
        }, files={"document": f})
    return result["result"]["message_id"]


def send_approval_buttons(cal_date: str, question: dict, part: dict) -> int:
    """Send inline keyboard for approval."""
    title = question.get("title", "Unknown")
    part_str = f" Part {part['part_number']}/{part['total_parts']}" if part['total_parts'] > 1 else ""

    text = (
        f"*Content Preview — {cal_date}*\n\n"
        f"📌 *{title}{part_str}*\n"
        f"🏢 {question.get('companies','').upper()}\n"
        f"📊 {question.get('difficulty','').title()} · {question.get('pattern','').replace('_',' ').title()}\n"
        f"🔢 Depth score: {question.get('depth_score',3)}/10\n\n"
        f"Review the videos and carousel above ↑\n"
        f"Auto-approves in {AUTO_APPROVE_MINUTES} min if no response."
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve All", "callback_data": f"approve:{cal_date}"},
                {"text": "⏭ Skip Today", "callback_data": f"skip:{cal_date}"},
            ],
            [
                {"text": "🔄 Regen Hook", "callback_data": f"regen:hook:{cal_date}"},
                {"text": "🔄 Regen Captions", "callback_data": f"regen:copy:{cal_date}"},
            ],
            [
                {"text": "🔄 Regen All", "callback_data": f"regen:all:{cal_date}"},
                {"text": "📅 Reschedule +1 Day", "callback_data": f"reschedule:{cal_date}"},
            ],
        ]
    }
    result = _send("sendMessage", json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": keyboard,
    })
    return result["result"]["message_id"]


def send_morning_preview(
    question: dict, part: dict, cal_date: str,
    video_paths: dict, copy_paths: dict, carousel_paths: dict
) -> int:
    """
    Full morning preview sequence:
    1. Send header text
    2. Send 4 short videos
    3. Send carousel PDF
    4. Send LinkedIn caption
    5. Send approval keyboard
    Returns telegram_msg_id of approval message.
    """
    if not BOT_TOKEN or not CHAT_ID:
        print("[telegram] No credentials — skipping preview. Auto-continuing.")
        return 0

    title = question.get("title", "")
    part_str = f" · Part {part['part_number']}/{part['total_parts']}" if part['total_parts'] > 1 else ""

    # Header
    send_text(f"🌅 *Good morning! Daily content ready for review.*\n\n*{title}{part_str}*")
    time.sleep(1)

    # 4 shorts
    short_labels = {
        "hook": "Short 1/4 — Hook (FOMO bait)",
        "dry_run": "Short 2/4 — Dry Run (pure animation)",
        "code": "Short 3/4 — Code Reveal (Python + Java)",
        "dialogue": "Short 4/4 — Interview Dialogue",
    }
    for short_type, label in short_labels.items():
        vpath = video_paths.get(f"short_{short_type}")
        if vpath and Path(vpath).exists():
            try:
                send_video(vpath, caption=f"*{label}*")
                time.sleep(2)
            except Exception as e:
                send_text(f"⚠️ Couldn't send {short_type} video: {e}")
        else:
            send_text(f"⚠️ {label}: video not rendered (path: {vpath})")

    # Carousel
    pdf_path = carousel_paths.get("pdf")
    if pdf_path and Path(pdf_path).exists():
        li_caption = ""
        li_path = copy_paths.get("linkedin")
        if li_path and Path(li_path).exists():
            li_caption = open(li_path).read()[:1000]
        send_document(pdf_path, caption=f"📊 *LinkedIn Carousel + Caption:*\n\n{li_caption}")
        time.sleep(1)

    # Approval buttons
    msg_id = send_approval_buttons(cal_date, question, part)
    return msg_id


def wait_for_approval(cal_date: str, timeout_minutes: int = None) -> str:
    """
    Poll for Telegram callback. Returns 'approved' | 'skip' | 'timeout'.
    Handles regen callbacks by returning 'regen:<type>'.
    """
    if not BOT_TOKEN or not CHAT_ID:
        return "approved"  # No bot = auto-approve

    timeout_minutes = timeout_minutes or AUTO_APPROVE_MINUTES
    deadline = time.time() + timeout_minutes * 60
    offset = 0

    print(f"[telegram] Waiting for approval (timeout: {timeout_minutes} min)...")

    while time.time() < deadline:
        try:
            updates = _send("getUpdates", json={"offset": offset, "timeout": 30})
            for update in updates.get("result", []):
                offset = update["update_id"] + 1
                callback = update.get("callback_query")
                if not callback:
                    continue

                data = callback.get("data", "")
                # Answer the callback to remove loading spinner
                _send("answerCallbackQuery", json={"callback_query_id": callback["id"]})

                if data == f"approve:{cal_date}":
                    db.set_calendar_status(cal_date, "approved")
                    send_text(f"✅ Approved! Posting will begin at scheduled times.")
                    return "approved"

                elif data == f"skip:{cal_date}":
                    db.set_calendar_status(cal_date, "skipped")
                    send_text(f"⏭ Skipped. Tomorrow's content will post as normal.")
                    return "skip"

                elif data.startswith(f"regen:") and data.endswith(f":{cal_date}"):
                    regen_type = data.split(":")[1]
                    send_text(f"🔄 Regenerating {regen_type}... (~2 min)")
                    return f"regen:{regen_type}"

                elif data == f"reschedule:{cal_date}":
                    send_text(f"📅 Rescheduled to tomorrow.")
                    return "reschedule"

        except Exception as e:
            print(f"[telegram] Poll error: {e}")
            time.sleep(5)

    # Timeout — auto-approve
    print(f"[telegram] Timeout reached — auto-approving.")
    db.set_calendar_status(cal_date, "approved")
    send_text(f"⏰ No response in {timeout_minutes} min — auto-approved and posting now.")
    return "approved"


def send_post_result(platform: str, status: str, url: str = "", error: str = ""):
    """Send posting result notification."""
    if not BOT_TOKEN or not CHAT_ID:
        return
    emoji = "✅" if status == "success" else "❌"
    text = f"{emoji} *{platform.title()}*: {status.upper()}"
    if url:
        text += f"\n🔗 {url}"
    if error:
        text += f"\n⚠️ Error: {error[:200]}"
    try:
        send_text(text)
    except Exception:
        pass


def send_error_alert(platform: str, error: str, cal_date: str, manual_url: str = ""):
    """Send failure alert with manual post option."""
    if not BOT_TOKEN or not CHAT_ID:
        return
    text = (
        f"Posting failed - {platform}\n\n"
        f"Date: {cal_date}\n"
        f"Error: {error[:300]}\n\n"
        f"{'Manual upload: ' + manual_url if manual_url else 'Check GitHub Actions logs.'}\n\n"
        f"Reply /retry_{platform.lower().replace(' ', '_')} to retry."
    )
    try:
        # Send as plain text to avoid markdown parse errors from raw exception strings.
        send_text(text, parse_mode=None)
    except Exception as e:
        print(f"[telegram] Alert send failed: {e}")


if __name__ == "__main__":
    # Test connection
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN not set")
    else:
        result = send_text("🤖 DSA Content Bot is alive! Ready for daily previews.")
        print(f"Test message sent: {result}")
