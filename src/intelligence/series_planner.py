"""
series_planner.py — AI-driven series planning.
For depth_score >= 7: Gemini splits into N parts, each scheduled on consecutive calendar days.
For depth_score < 7: single-day, all 4 shorts cover the same topic from different angles.
"""

import os
import json
import re
from datetime import date, timedelta
import google.generativeai as genai
import db

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)
MODEL = "gemini-1.5-flash"

DEPTH_THRESHOLD = 7   # >= this → multi-part series


def plan_series(question: dict) -> list[dict]:
    """
    Ask Gemini to plan parts for this question.
    Returns list of parts: [{"part_number":1,"part_title":"...","part_focus":"...","short_angles":[...]}]
    """
    depth = question.get("depth_score", 3)

    if depth < DEPTH_THRESHOLD:
        # Shallow: 1 part, 4 different short angles on same topic
        return [_single_part(question)]

    # Deep: ask Gemini to plan N parts
    prompt = f"""You are a content strategist for a DSA YouTube channel targeting FAANG aspirants in India.

Question: {question['title']}
Category: {question['category']}
Pattern: {question.get('pattern','')}
Depth score: {depth}/10
Description: {question.get('description','')}
Approach: {question.get('approach','')}

This is a DEEP topic (depth >= 7). Split it into {_recommended_parts(depth)} parts for a video series.
Each part = one day of content (4 shorts + 1 long-form).

Rules:
- Part 1: Always starts with BRUTE FORCE / NAIVE approach + why it fails
- Middle parts: Optimal approach, dry run, code walkthrough  
- Last part: Variations, follow-up questions interviewers ask, edge cases, real-world applications
- Each part must be independently watchable (brief recap of prev part)
- part_focus: exactly what this part covers (2-3 sentences)
- short_angles: exactly 4 different short angles for this part:
  * "hook" - the FOMO/failure angle (no solution)
  * "dry_run" - pure animation of the key step in this part
  * "code" - code reveal for this part's solution
  * "dialogue" - interviewer-candidate dialogue about this specific concept

Return ONLY valid JSON array:
[
  {{
    "part_number": 1,
    "total_parts": N,
    "part_title": "Short catchy title for this part",
    "part_focus": "What this part covers in 2-3 sentences.",
    "short_angles": {{
      "hook": "What failure angle to use for hook short",
      "dry_run": "What specific step/concept to animate",
      "code": "What code to reveal (brute/optimal/specific function)",
      "dialogue": "What specific interview question to dialogue about"
    }}
  }},
  ...
]"""

    model = genai.GenerativeModel(model_name=MODEL)
    resp = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(temperature=0.4, max_output_tokens=2048)
    )
    raw = resp.text.strip()
    raw = re.sub(r'^```json\n?', '', raw)
    raw = re.sub(r'^```\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw)

    try:
        parts = json.loads(raw)
        # Validate structure
        for p in parts:
            assert "part_number" in p and "part_title" in p and "part_focus" in p
        return parts
    except Exception as e:
        print(f"[series] Gemini parse failed ({e}), falling back to 2-part split")
        return _fallback_two_parts(question)


def _recommended_parts(depth: int) -> int:
    if depth <= 7: return 2
    if depth <= 8: return 3
    return 4


def _single_part(question: dict) -> dict:
    return {
        "part_number": 1,
        "total_parts": 1,
        "part_title": question["title"],
        "part_focus": question.get("description", ""),
        "short_angles": {
            "hook": f"The mistake candidates make with {question['title']}",
            "dry_run": f"Step-by-step dry run of {question.get('pattern','').replace('_',' ')} approach",
            "code": f"Optimal Python + Java solution for {question['title']}",
            "dialogue": f"Interviewer asks {question['title']} — perfect response walkthrough",
        }
    }


def _fallback_two_parts(question: dict) -> list[dict]:
    return [
        {
            "part_number": 1, "total_parts": 2,
            "part_title": f"{question['title']} — Intuition & Brute Force",
            "part_focus": "Understanding the problem and why brute force fails. Building intuition for optimal approach.",
            "short_angles": {
                "hook": f"Why everyone gets {question['title']} wrong in interviews",
                "dry_run": "Brute force animation showing inefficiency",
                "code": "Brute force code and why it TLEs",
                "dialogue": "Interviewer catches you with brute force — how to respond",
            }
        },
        {
            "part_number": 2, "total_parts": 2,
            "part_title": f"{question['title']} — Optimal Solution & Follow-ups",
            "part_focus": f"The {question.get('approach','')}. Code walkthrough, complexity analysis, interview follow-ups.",
            "short_angles": {
                "hook": "The one insight that unlocks the optimal solution",
                "dry_run": "Optimal approach animated step by step",
                "code": "Clean optimal solution with complexity",
                "dialogue": "Interviewer follow-up questions — handled perfectly",
            }
        }
    ]


def schedule_series(question: dict, parts: list[dict], start_date: date) -> list[tuple]:
    """
    Write series parts to DB and assign calendar dates.
    Returns list of (date_str, part_dict) tuples.
    """
    db.upsert_series(question["slug"], parts)
    scheduled = []
    for i, part in enumerate(parts):
        cal_date = (start_date + timedelta(days=i)).isoformat()
        db.set_calendar_entry(
            for_date=cal_date,
            question_slug=question["slug"],
            part_number=part["part_number"],
            total_parts=part["total_parts"],
        )
        scheduled.append((cal_date, part))
        print(f"[series] Scheduled Part {part['part_number']}/{part['total_parts']}: {cal_date} — {part['part_title']}")
    return scheduled


def get_or_plan_today(question: dict, today: date) -> dict:
    """
    For today's calendar entry, return the correct part plan.
    If single-part: returns the one part.
    If multi-part: checks if series already planned (in DB), gets today's part.
    """
    depth = question.get("depth_score", 3)

    if depth < DEPTH_THRESHOLD:
        return _single_part(question)

    # Check if series already planned in DB
    existing = db.get_series_parts(question["slug"])
    if existing:
        # Find the part that matches today's calendar entry
        cal = db.get_calendar_entry(today.isoformat())
        part_num = cal["part_number"] if cal else 1
        for p in existing:
            if p["part_number"] == part_num:
                return {
                    "part_number": p["part_number"],
                    "total_parts": p["total_parts"],
                    "part_title": p["part_title"],
                    "part_focus": p["part_focus"],
                    "short_angles": json.loads(p.get("part_focus_json") or "{}") or _single_part(question)["short_angles"],
                }
        return _single_part(question)

    # Not planned yet — plan now and schedule
    print(f"[series] Planning series for: {question['title']} (depth={depth})")
    parts = plan_series(question)
    schedule_series(question, parts, today)
    return parts[0]  # Today is always Part 1


if __name__ == "__main__":
    # Test
    sample_deep = {
        "slug": "design-instagram-feed", "title": "Design Instagram Feed",
        "category": "system_design", "pattern": "system_design_hld",
        "difficulty": "hard", "depth_score": 9,
        "description": "500M DAU feed generation with celebrity problem.",
        "approach": "Hybrid push-pull with Kafka fan-out and Redis sorted set.",
    }
    parts = plan_series(sample_deep)
    print(f"\nPlanned {len(parts)} parts:")
    for p in parts:
        print(f"  Part {p['part_number']}: {p['part_title']}")
        print(f"    Focus: {p['part_focus'][:80]}...")
