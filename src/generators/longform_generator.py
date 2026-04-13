"""
longform_generator.py — Generates Manim script for 10-15 min deep-dive video.
3Blue1Brown whiteboard style with pointer annotations.
Includes chapter markers for YouTube timestamps.
"""

import os
import re
import json
from google import genai
from google.genai import types

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
_client = genai.Client(api_key=GEMINI_API_KEY)
MODEL = "gemini-1.5-flash"

LONGFORM_SYSTEM = """You are an expert Manim scriptwriter for long-form DSA/System Design educational videos.
Style: 3Blue1Brown whiteboard — clean, deliberate, every animation serves understanding.
Target length: 10-15 minutes at normal playback speed.

MANIM RULES:
- Use Manim Community Edition v0.18+ with manim-dsa plugin
- Class: `LongFormScene(Scene)`
- Import: `from manim import *` and `from manim_dsa import *`
- Use 1920x1080 landscape orientation
- Font sizes: 48px for titles, 36px for body text, 28px for code
- Colors: BLUE_D=primary, GREEN_D=correct, RED_D=wrong, YELLOW_D=highlight, WHITE=text
- Use VGroup for grouping related elements
- Use Transform() for transitions between states
- Use Write() for text, Create() for shapes, FadeIn/FadeOut for auxiliary elements
- Add chapter markers as Text comments: # CHAPTER: "Chapter Name" at 0:00
- self.wait() calls: 0.5s between steps, 1.5s after major reveals, 2s at chapter breaks
- Pointer: use Arrow() with annotation to highlight specific elements
- Code: use Code() Manim object, animate with Write() line by line

CHAPTER STRUCTURE (mandatory — enables YouTube timestamps):
  Chapter 1 "The Problem" (~90s): Problem statement + constraints + examples
  Chapter 2 "Brute Force" (~120s): Naive approach, animate it, show why it fails
  Chapter 3 "The Insight" (~90s): The key observation that unlocks optimal
  Chapter 4 "Optimal Approach" (~180s): Full dry run with pointer annotations
  Chapter 5 "Code Walkthrough" (~150s): Python then Java, line by line explanation
  Chapter 6 "Complexity Analysis" (~60s): Time + space with visual proof
  Chapter 7 "Follow-up Questions" (~90s): 2-3 variants the interviewer will ask

END with CTA screen: "Follow for daily FAANG patterns" + channel name placeholder

RETURN ONLY VALID PYTHON CODE. No markdown fences. No explanation."""


def generate_longform_script(question: dict, part: dict, output_dir: str) -> str:
    """Generate long-form Manim script. Returns file path."""
    os.makedirs(output_dir, exist_ok=True)

    category = question.get("category", "dsa")
    is_sd = category in ("system_design", "lld")

    user_prompt = f"""Generate a complete long-form Manim animation script for:

Title: {question['title']}
Part: {part['part_title']} ({part['part_number']}/{part['total_parts']})
Category: {category}
Pattern: {question.get('pattern','').replace('_',' ')}
Difficulty: {question.get('difficulty','medium')}
Companies: {question.get('companies','')}

Part focus (what THIS video covers):
{part['part_focus']}

Description:
{question.get('description','')}

Dry run example:
{question.get('dry_run','')}

Approach:
{question.get('approach','')}

What interviewers want:
{question.get('what_interviewers_want','')}

Python code:
{question.get('python_code','# Python solution')}

Java code:
{question.get('java_code','// Java solution')}

{'SYSTEM DESIGN SPECIFIC: Use box diagrams with arrows. Animate each component appearing one by one. Show data flow with moving dots along arrows. Use colored regions for different layers (client/server/DB/cache).' if is_sd else 'DSA SPECIFIC: Use MArray/MStack/MGraph from manim_dsa. Show variable state panel. Use pointer arrows for indices. Color-code: GREEN=correct, RED=discard, YELLOW=current.'}

The class must be named `LongFormScene`."""

    resp = _client.models.generate_content(
        model=MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=LONGFORM_SYSTEM,
            temperature=0.25,
            max_output_tokens=8192,
        ),
    )

    script = resp.text.strip()
    # Strip any accidental markdown
    script = re.sub(r'^```python\n?', '', script)
    script = re.sub(r'^```\n?', '', script)
    script = re.sub(r'\n?```$', '', script)
    script = script.strip()

    # Inject config comment at top
    config_header = "# config: --resolution 1920,1080 --frame_rate 30 -qm\n\n"
    if not script.startswith("#"):
        script = config_header + script

    path = os.path.join(output_dir, "longform_scene.py")
    with open(path, "w") as f:
        f.write(script)

    print(f"[longform] Script saved: {path} ({len(script)} chars)")
    return path


def extract_chapter_timestamps(script_path: str) -> list[dict]:
    """
    Parse # CHAPTER: "Name" comments from script to build YouTube timestamps.
    Returns [{"time": "0:00", "title": "The Problem"}, ...]
    Timestamps are estimated based on chapter order and average duration.
    """
    chapter_durations = [90, 120, 90, 180, 150, 60, 90]  # seconds per chapter
    chapters = []

    with open(script_path) as f:
        content = f.read()

    matches = re.findall(r'#\s*CHAPTER:\s*["\'](.+?)["\']', content)
    if not matches:
        # Fallback: standard chapter names
        matches = ["The Problem", "Brute Force", "The Insight",
                   "Optimal Approach", "Code Walkthrough",
                   "Complexity Analysis", "Follow-up Questions"]

    elapsed = 0
    for i, title in enumerate(matches):
        mins, secs = divmod(elapsed, 60)
        chapters.append({"time": f"{mins}:{secs:02d}", "title": title})
        elapsed += chapter_durations[i] if i < len(chapter_durations) else 90

    return chapters


def build_youtube_description_with_timestamps(
    question: dict, part: dict, chapters: list[dict], channel_handle: str = "@YourChannel"
) -> str:
    """Build full YouTube description with timestamps."""
    companies = question.get("companies", "").replace(",", " · ").upper()
    pattern = question.get("pattern", "").replace("_", " ").title()
    part_str = f" | Part {part['part_number']}/{part['total_parts']}" if part['total_parts'] > 1 else ""

    timestamp_block = "\n".join(f"{c['time']} {c['title']}" for c in chapters)

    return f"""{question['title']}{part_str} — {pattern} | FAANG Interview Guide

{part['part_focus']}

Asked at: {companies}
Difficulty: {question.get('difficulty','').upper()} | Pattern: {pattern}

⏱ TIMESTAMPS
{timestamp_block}

📌 What you'll learn:
• Why the brute force approach gets you rejected
• The key insight {question.get('what_interviewers_want','')[:100]}
• Clean Python + Java solutions with full explanation
• Follow-up questions interviewers will ask

💡 Related patterns: {', '.join(question.get('pattern','').split('_'))}

Subscribe {channel_handle} for daily FAANG interview patterns.
New video every day at 6 AM IST.

#DSA #LeetCode #FAANG #CodingInterview #{pattern.replace(' ','')} #MAANG #SWEIndia"""


if __name__ == "__main__":
    sample = {
        "slug": "two-sum", "title": "Two Sum", "category": "dsa",
        "pattern": "two_pointer", "difficulty": "easy",
        "companies": "google,amazon,meta",
        "description": "Given array and target, return indices of two numbers summing to target.",
        "dry_run": "nums=[2,7,11,15], target=9 → hash map → return [0,1]",
        "approach": "Hash map. O(n) time O(n) space.",
        "what_interviewers_want": "Recognize hash map over O(n²). Clarify constraints.",
        "python_code": "def twoSum(nums, target):\n    seen={}\n    for i,n in enumerate(nums):\n        if target-n in seen: return [seen[target-n],i]\n        seen[n]=i",
        "java_code": "public int[] twoSum(int[] nums, int target) { ... }",
    }
    part = {"part_number": 1, "total_parts": 1,
            "part_title": "Two Sum", "part_focus": "Hash map approach from brute force to optimal."}
    path = generate_longform_script(sample, part, "/tmp/test_longform")
    print(f"Script: {path}")
    chapters = extract_chapter_timestamps(path)
    desc = build_youtube_description_with_timestamps(sample, part, chapters)
    print(f"\nDescription preview:\n{desc[:500]}")
