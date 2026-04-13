"""
calendar_planner.py — Runs every Sunday to plan the next 7 days.
Enforces: pattern variety, difficulty curve, SD/LLD quota, series continuity.
"""

import os
import json
import random
from datetime import date, timedelta
from google import genai
import db
import sys
sys.path.insert(0, "..")
import question_bank as qb

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
_client = genai.Client(api_key=GEMINI_API_KEY)

# Weekly content quotas
WEEKLY_QUOTA = {
    "system_design": 2,   # Wednesday + Sunday
    "lld": 1,             # Saturday
    "cs_fundamentals": 1, # Friday
    "dsa": 3,             # Mon, Tue, Thu
}

DIFFICULTY_MAP = {
    0: "easy",    # Monday
    1: "medium",  # Tuesday
    2: None,      # Wednesday → SD (any diff)
    3: "medium",  # Thursday
    4: "hard",    # Friday
    5: None,      # Saturday → LLD
    6: None,      # Sunday → SD
}


def plan_week(start_monday: date) -> list[dict]:
    """
    Plan 7 days starting from the given Monday.
    Returns list of {date, question_slug, part_number, total_parts, category}.
    """
    posted = db.get_posted_slugs()
    recent_patterns = db.get_recent_patterns(days=14)  # look back 2 weeks for variety
    bank = qb.load_bank()

    plan = []
    used_patterns = []
    used_categories = {}

    print(f"\n[calendar] Planning week of {start_monday.isoformat()}")

    for day_offset in range(7):
        day = start_monday + timedelta(days=day_offset)
        weekday = day.weekday()  # 0=Mon ... 6=Sun
        day_str = day.isoformat()

        # Check if already planned
        existing = db.get_calendar_entry(day_str)
        if existing and existing["status"] not in ("pending",):
            print(f"  {day_str}: already scheduled ({existing['status']})")
            plan.append(existing)
            continue

        # Determine category for this day
        if weekday in (2, 6):    # Wed, Sun
            category = "system_design"
        elif weekday == 5:       # Sat
            category = "lld"
        elif weekday == 4:       # Fri
            category = "cs_fundamentals"
        else:                    # Mon, Tue, Thu
            category = "dsa"

        target_difficulty = DIFFICULTY_MAP[weekday]

        # Check if we're mid-series (a deep question spans multiple days)
        mid_series = _check_mid_series(bank, posted, day_str)
        if mid_series:
            print(f"  {day_str}: continuing series — {mid_series['title']} Part {mid_series['next_part']}")
            db.set_calendar_entry(day_str, mid_series["slug"], mid_series["next_part"], mid_series["total_parts"])
            plan.append({"cal_date": day_str, "question_slug": mid_series["slug"],
                         "part_number": mid_series["next_part"], "total_parts": mid_series["total_parts"]})
            continue

        # Pick best question for this day
        candidates = [q for q in bank
                      if q["slug"] not in posted
                      and q["category"] == category
                      and q["pattern"] not in used_patterns[-3:]  # no same pattern 3 days in a row
                      and (target_difficulty is None or q["difficulty"] == target_difficulty or
                           (target_difficulty == "hard" and q["difficulty"] in ("medium", "hard")))]

        if not candidates:
            # Relax constraints
            candidates = [q for q in bank
                          if q["slug"] not in posted and q["category"] == category]

        if not candidates:
            print(f"  {day_str}: WARNING — no candidates for category={category}")
            continue

        # Score and pick
        scored = sorted(candidates,
                        key=lambda q: qb.score(q, recent_patterns + used_patterns, posted),
                        reverse=True)
        question = random.choice(scored[:3])

        print(f"  {day_str} ({['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][weekday]}): "
              f"{question['title']} (depth={question['depth_score']}, diff={question['difficulty']})")

        db.set_calendar_entry(day_str, question["slug"], 1, question.get("total_parts", 1))
        used_patterns.append(question.get("pattern", ""))

        plan.append({
            "cal_date": day_str,
            "question_slug": question["slug"],
            "part_number": 1,
            "total_parts": question.get("total_parts", 1),
            "category": category,
        })

        # If deep question, pre-schedule subsequent parts on following days
        from intelligence.series_planner import DEPTH_THRESHOLD, plan_series, schedule_series
        if question.get("depth_score", 3) >= DEPTH_THRESHOLD:
            parts = plan_series(question)
            if len(parts) > 1:
                # Schedule parts 2..N on subsequent days
                for extra_offset, part in enumerate(parts[1:], 1):
                    future_day = (day + timedelta(days=extra_offset)).isoformat()
                    db.set_calendar_entry(future_day, question["slug"],
                                         part["part_number"], part["total_parts"])
                    print(f"    → Part {part['part_number']}: {future_day}")

    return plan


def _check_mid_series(bank: list, posted: set, day_str: str) -> dict | None:
    """Check if there's an ongoing series that needs continuation on this day."""
    # Look at yesterday's calendar entry
    yesterday = (date.fromisoformat(day_str) - timedelta(days=1)).isoformat()
    yesterday_entry = db.get_calendar_entry(yesterday)
    if not yesterday_entry:
        return None

    slug = yesterday_entry["question_slug"]
    ypart = yesterday_entry["part_number"]
    ytotal = yesterday_entry["total_parts"]

    if ypart >= ytotal:
        return None  # series complete

    # There's a next part to post
    q = db.get_question(slug)
    if not q:
        for item in bank:
            if item["slug"] == slug:
                q = item
                break

    return {
        "slug": slug,
        "title": q["title"] if q else slug,
        "next_part": ypart + 1,
        "total_parts": ytotal,
    }


def format_telegram_preview(plan: list) -> str:
    """Format weekly plan as Telegram message for preview."""
    lines = ["📅 *Content Calendar — Next 7 Days*\n"]
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for entry in plan:
        d = date.fromisoformat(entry["cal_date"])
        day_name = days[d.weekday()]
        slug = entry.get("question_slug", "?")
        part = entry.get("part_number", 1)
        total = entry.get("total_parts", 1)
        part_str = f" (Part {part}/{total})" if total > 1 else ""

        q = db.get_question(slug)
        title = q["title"] if q else slug

        lines.append(f"*{day_name} {entry['cal_date']}*: {title}{part_str}")

    lines.append("\nReply /swap <date> to change any day.")
    return "\n".join(lines)


if __name__ == "__main__":
    from datetime import date
    today = date.today()
    # Find next Monday
    days_to_monday = (7 - today.weekday()) % 7
    if days_to_monday == 0:
        days_to_monday = 7
    monday = today + timedelta(days=days_to_monday)
    plan = plan_week(monday)
    print(f"\nPlan: {len(plan)} days scheduled")
