"""
main.py — v2 Daily pipeline orchestrator.
Runs at 6 AM IST via GitHub Actions cron.

Flow:
  0. init_db
  1. load today's calendar entry (planned by Sunday's calendar_planner.py)
  2. plan series parts if deep question (series_planner.py)
  3. generate 4 Manim short scripts + voiceover scripts (shorts_generator.py)
  4. generate long-form Manim script
  5. render all 5 videos (GitHub Actions matrix handles parallelism)
  6. generate LinkedIn carousel (carousel_generator.py)
  7. generate all copy: LinkedIn + 4 Instagram + 5 YouTube (copy_writer.py)
  8. send Telegram preview + wait for approval
  9. post at staggered times (platform_poster.py)
  10. mark posted in DB + commit state.db
"""

import os
import sys
import json
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "generators"))
sys.path.insert(0, str(Path(__file__).parent / "intelligence"))

import db
import question_bank as qb
from intelligence.series_planner import get_or_plan_today, DEPTH_THRESHOLD
from generators.shorts_generator import generate_all_shorts
from generators.carousel_generator import generate_carousel
from generators.copy_writer import generate_all_copy
import telegram_bot as tg

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
VIDEO_ONLY = os.environ.get("VIDEO_ONLY", "false").lower() == "true"  # For parallel render step
TODAY = os.environ.get("OVERRIDE_DATE", date.today().isoformat())
OUTPUT_DIR = os.path.join("output", TODAY)


def banner(step: str, msg: str):
    print(f"\n{'─'*60}")
    print(f"  {step} | {msg}")
    print(f"{'─'*60}")


def run():
    banner("START", f"DSA Content Engine v2 — {TODAY} | DRY_RUN={DRY_RUN}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── Step 0: DB init ──────────────────────────────────────────────
    banner("0/8", "Database init")
    db.init_db()
    stats = db.count_questions()
    print(f"  Bank: {stats['total']} total, {stats['posted']} posted, {stats['remaining']} remaining")
    if stats["remaining"] < 30:
        print("  ⚠️  WARNING: Bank below 30 questions. Trigger refresh_bank workflow.")

    # ── Step 1: Load today's question ────────────────────────────────
    banner("1/8", "Load today's calendar entry")
    cal = db.get_calendar_entry(TODAY)

    if not cal:
        print("  No calendar entry for today — auto-picking question...")
        bank = qb.load_bank()
        posted = db.get_posted_slugs()
        recent = db.get_recent_patterns(days=7)

        # Category: SD on Wed(2)/Sun(6), LLD on Sat(5), CS on Fri(4), DSA otherwise
        weekday = date.today().weekday()
        cat_map = {2: "system_design", 5: "lld", 4: "cs_fundamentals", 6: "system_design"}
        category = cat_map.get(weekday, "dsa")

        question_data = qb.pick_today(category, posted, recent)
        db.upsert_question({**question_data, "added_at": datetime.utcnow().isoformat()})
        db.set_calendar_entry(TODAY, question_data["slug"], 1, question_data.get("total_parts", 1))
        cal = db.get_calendar_entry(TODAY)

    if cal["status"] == "skipped":
        print("  Today marked as skipped. Exiting.")
        return

    slug = cal["question_slug"]
    part_num = cal["part_number"]
    total_parts = cal["total_parts"]
    print(f"  Question: {slug} (Part {part_num}/{total_parts})")

    # Load question from DB or bank
    question = db.get_question(slug)
    if not question:
        bank = qb.load_bank()
        for q in bank:
            if q["slug"] == slug:
                db.upsert_question({**q, "added_at": datetime.utcnow().isoformat()})
                question = db.get_question(slug)
                break
    if not question:
        print(f"  ERROR: question {slug} not found!")
        sys.exit(1)

    print(f"  Title: {question['title']}")
    print(f"  Category: {question['category']} | Depth: {question.get('depth_score',3)}/10")

    # ── Step 2: Series planning ──────────────────────────────────────
    banner("2/8", "Series planning")
    part = get_or_plan_today(question, date.today())
    print(f"  Part title: {part['part_title']}")
    print(f"  Focus: {part['part_focus'][:80]}...")

    # Save part context to output
    with open(f"{OUTPUT_DIR}/part_context.json", "w") as f:
        json.dump({"question": dict(question), "part": part, "cal_date": TODAY}, f, indent=2)

    # ── Step 3: Generate short scripts ──────────────────────────────
    banner("3/8", "Generating 4 short animation scripts (Gemini)")
    shorts_script_dir = f"{OUTPUT_DIR}/scripts/shorts"
    short_scripts = generate_all_shorts(question, part, shorts_script_dir)
    print(f"  Scripts: {list(short_scripts.keys())}")

    # ── Step 4: Long-form script ─────────────────────────────────────
    banner("4/8", "Generating long-form script (Gemini)")
    from generators.longform_generator import generate_longform_script
    longform_script = generate_longform_script(question, part, f"{OUTPUT_DIR}/scripts")
    print(f"  Long-form script: {longform_script}")

    if VIDEO_ONLY:
        print("\n  VIDEO_ONLY mode — stopping after script generation.")
        print("  GitHub Actions render job will pick these up.")
        return

    # ── Step 5: Render videos ────────────────────────────────────────
    # Note: In production, GitHub Actions matrix renders shorts in parallel.
    # Here we call the render sequentially for simplicity.
    banner("5/8", "Rendering videos (Manim + Kokoro TTS)")
    from generators.video_renderer import render_all
    video_paths = render_all(question, part, short_scripts, longform_script, OUTPUT_DIR)
    print(f"  Rendered: {list(video_paths.keys())}")

    # ── Step 6: LinkedIn carousel ────────────────────────────────────
    banner("6/8", "Generating LinkedIn carousel (Pillow)")
    carousel_dir = f"{OUTPUT_DIR}/carousel"
    carousel_paths = generate_carousel(question, part, carousel_dir)
    print(f"  Carousel: {carousel_paths.get('pdf','no pdf')}")

    # ── Step 7: Generate all copy ────────────────────────────────────
    banner("7/8", "Generating post copy (Gemini + Claude Haiku review)")
    copy_dir = f"{OUTPUT_DIR}/copy"
    copy_paths = generate_all_copy(question, part, copy_dir)

    # ── Step 8: Telegram preview (optional, non-blocking) ────────────
    banner("8/9", "Telegram preview")
    HAS_TELEGRAM = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))
    if DRY_RUN:
        print("  DRY_RUN — skipping Telegram.")
    elif HAS_TELEGRAM:
        try:
            msg_id = tg.send_morning_preview(
                question, part, TODAY, video_paths, copy_paths, carousel_paths
            )
            db.set_calendar_entry(TODAY, slug, part_num, total_parts, telegram_msg_id=msg_id)
            print("  Preview sent to Telegram.")
        except Exception as e:
            print(f"  Telegram preview failed (non-fatal): {e}")
    else:
        print("  TELEGRAM_BOT_TOKEN not set — skipping preview.")

    # ── Step 9: Upload all content to Google Drive ────────────────────
    banner("9/9", "Uploading all content to Google Drive")
    results = {}
    if not DRY_RUN:
        db.set_calendar_status(TODAY, "uploading")
        try:
            from posters.drive_uploader import upload_all_to_drive
            results = upload_all_to_drive(
                question, part, TODAY, video_paths, copy_paths, carousel_paths
            )
            print(f"  Uploaded: {len(results.get('uploaded', []))} files")
            if results.get("errors"):
                print(f"  Errors:   {results['errors']}")

            final_status = "done" if results["status"] == "success" else "partial"
            db.set_calendar_status(TODAY, final_status)

            if HAS_TELEGRAM:
                try:
                    err_note = f", {len(results['errors'])} errors" if results.get("errors") else ""
                    tg.send_text(
                        f"✅ *Content ready — {TODAY}*\n"
                        f"*{question['title']}* — Part {part_num}/{total_parts}\n\n"
                        f"📁 [All files]({results['date_folder_link']})\n"
                        f"▶️ [YouTube]({results['youtube_folder_link']})\n"
                        f"📸 [Instagram]({results['instagram_folder_link']})\n"
                        f"💼 [LinkedIn]({results['linkedin_folder_link']})\n\n"
                        f"_{len(results.get('uploaded', []))} files uploaded{err_note}_"
                    )
                except Exception as e:
                    print(f"  Telegram summary failed (non-fatal): {e}")

        except Exception as e:
            print(f"  Drive upload failed: {e}")
            db.set_calendar_status(TODAY, "failed")
            if HAS_TELEGRAM:
                try:
                    tg.send_error_alert("Drive upload", str(e), TODAY)
                except Exception:
                    pass
    else:
        results = {"status": "dry_run", "uploaded": [], "errors": []}
        print("  DRY_RUN — skipping Drive upload.")

    banner("DONE", f"{question['title']} | Part {part_num}/{total_parts} | {results.get('status', 'unknown')}")


if __name__ == "__main__":
    run()
