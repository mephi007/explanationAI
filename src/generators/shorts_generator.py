"""
shorts_generator.py — Generates 4 different Manim animation scripts per question/part.
Each short has a distinct purpose and angle as defined by series_planner.

Short types:
  1. hook       — FOMO/failure bait. No solution shown. Creates urgency to follow.
  2. dry_run    — Pure animation. Step-by-step, no talking head. High rewatch value.
  3. code       — Code reveal character by character. Python + Java side by side.
  4. dialogue   — Two-voice interviewer/candidate. Most shareable format.
"""

import os
import re
import json
import google.generativeai as genai

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)
MODEL = "gemini-1.5-flash"

# ─── Shared Manim spec injected into every prompt ────────────────────────────
MANIM_SPEC = """
MANIM TECHNICAL RULES (non-negotiable):
- Use Manim Community Edition v0.18+
- Import: `from manim import *` and `from manim_dsa import *`
- Class name: MUST be `MainScene(Scene)`
- Portrait 9:16: config already set externally — design for tall narrow canvas
- Colors: GREEN_D=correct/found, RED_D=wrong/discard, YELLOW_D=current/highlight, BLUE_D=neutral
- Font: use Text() with font_size=36 for labels, 28 for subtitles in portrait
- Always self.wait(0.3) between logical steps for voice sync
- End with self.wait(1.0)
- NO external file reads — all data hardcoded
- Keep under 70 seconds total animation time
- RETURN ONLY VALID PYTHON CODE — no markdown, no explanation
"""

# ─── SHORT 1: HOOK ────────────────────────────────────────────────────────────
HOOK_SYSTEM = f"""You write Manim animation scripts for 60-second "hook" shorts.
Purpose: create FOMO. Show the WRONG approach, show it failing, tease the right answer WITHOUT revealing it.
Viewer emotion target: "Oh no, that's what I would have said. I need to follow this channel."

Structure (stick to this exactly):
  0-8s:  Title card — question title + company badge (Google/Amazon/Meta logo text)
  8-25s: "What 90% of candidates say" — animate the brute force / wrong approach
  25-45s: "Why the interviewer rejects this" — show O(n²) time limit exceeded or wrong output
  45-55s: "The insight that gets you hired" — show a QUESTION MARK, NOT the answer. Text: "Watch Part 2 →"
  55-60s: Channel name / subscribe CTA

{MANIM_SPEC}"""

# ─── SHORT 2: DRY RUN ─────────────────────────────────────────────────────────
DRY_RUN_SYSTEM = f"""You write Manim animation scripts for 75-second "dry run" shorts.
Purpose: pure educational value. Zero intro. Animation starts immediately frame 1.
Style: 3Blue1Brown whiteboard — clean, precise, pointer annotations.

Structure:
  0-5s:   Data structure appears (array, graph, tree) with example values
  5-65s:  Step-by-step execution. Each step: highlight → pointer moves → state updates → wait(0.3)
           Use MArray/MStack/MGraph from manim_dsa where applicable
           Add step counter "Step 3/7" top right
           Show variable state panel bottom left (e.g., "left=2, right=5, max=9")
  65-70s: Final state with "Time: O(n) · Space: O(1)" appearing

NO voiceover guide needed — animation is self-explanatory.
{MANIM_SPEC}"""

# ─── SHORT 3: CODE REVEAL ─────────────────────────────────────────────────────
CODE_SYSTEM = f"""You write Manim animation scripts for 60-second "code reveal" shorts.
Purpose: satisfy the "just show me the code" audience. High save rate.

Structure:
  0-5s:   Problem name + "Python + Java" badge
  5-50s:  Code written character by character using Write() animation
           Left half: Python code. Right half: Java code (split screen in portrait = stacked)
           Comments appear BEFORE the line they explain (teaching style)
           Syntax: use Code() Manim object with appropriate language
  50-58s: Full code visible. "Time: O(?) · Space: O(?)" animates in below
  58-60s: "Code in comments ↓" text

{MANIM_SPEC}"""

# ─── SHORT 4: DIALOGUE ────────────────────────────────────────────────────────
DIALOGUE_SYSTEM = f"""You write Manim animation scripts for 45-second "interviewer dialogue" shorts.
Purpose: simulate the actual interview moment. Two speakers. Most shareable format.

Structure:
  0-5s:   "FAANG Interview Simulation" title + company badge
  5-40s:  Chat-style dialogue. Two columns:
           Left: "Interviewer" (calm blue bubble). Right: "You" (confident green bubble)
           Text appears word by word (Write animation or FadeIn by word)
           8-10 lines total. Candidate first answer is WRONG or incomplete.
           Interviewer probes. Candidate gives optimal answer. Interviewer: "Perfect."
  40-45s: "This exact exchange happens at Google, Amazon, Meta every week."

{MANIM_SPEC}"""

# ─── Generator ────────────────────────────────────────────────────────────────

def _call_gemini(system: str, user: str) -> str:
    model = genai.GenerativeModel(model_name=MODEL, system_instruction=system)
    resp = model.generate_content(
        user,
        generation_config=genai.GenerationConfig(temperature=0.3, max_output_tokens=4096)
    )
    raw = resp.text.strip()
    raw = re.sub(r'^```python\n?', '', raw)
    raw = re.sub(r'^```\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw)
    return raw.strip()


def generate_hook(question: dict, part: dict) -> str:
    prompt = f"""Generate the hook short animation for:
Title: {question['title']}
Part: {part['part_title']} ({part['part_number']}/{part['total_parts']})
Hook angle: {part['short_angles']['hook']}
Companies: {question.get('companies','')}
Difficulty: {question.get('difficulty','medium')}
Wrong approach to show: BRUTE FORCE or naive answer
What fails: {question.get('dry_run','')[:200]}"""
    return _call_gemini(HOOK_SYSTEM, prompt)


def generate_dry_run(question: dict, part: dict) -> str:
    prompt = f"""Generate the dry-run animation for:
Title: {question['title']}
Part: {part['part_title']} ({part['part_number']}/{part['total_parts']})
What to animate: {part['short_angles']['dry_run']}
Dry run example: {question.get('dry_run','')}
Pattern: {question.get('pattern','')}
Approach: {part['part_focus']}"""
    return _call_gemini(DRY_RUN_SYSTEM, prompt)


def generate_code_reveal(question: dict, part: dict) -> str:
    python_code = question.get("python_code", "# Python solution")
    java_code = question.get("java_code", "// Java solution")
    prompt = f"""Generate the code reveal animation for:
Title: {question['title']}
Part: {part['part_title']}
What code to show: {part['short_angles']['code']}
Python code:
{python_code}

Java code:
{java_code}

Complexity: {question.get('approach','')[-100:]}"""
    return _call_gemini(CODE_SYSTEM, prompt)


def generate_dialogue(question: dict, part: dict) -> str:
    prompt = f"""Generate the interview dialogue animation for:
Title: {question['title']}
Part: {part['part_title']}
Dialogue topic: {part['short_angles']['dialogue']}
What interviewers want: {question.get('what_interviewers_want','')}
Company: {(question.get('companies','google').split(',')[0]).title()}

Write an 8-10 line dialogue where:
- Interviewer asks about: {part['short_angles']['dialogue']}
- Candidate first answer: slightly wrong or incomplete
- Interviewer probes: "Think about the time complexity..."
- Candidate corrects: gives the optimal insight
- Interviewer: "Exactly. That's the {question.get('pattern','').replace('_',' ')} pattern."
Make it feel real — tense but ultimately satisfying."""
    return _call_gemini(DIALOGUE_SYSTEM, prompt)


def generate_all_shorts(question: dict, part: dict, output_dir: str) -> dict:
    """Generate all 4 short scripts. Returns dict of paths."""
    os.makedirs(output_dir, exist_ok=True)
    paths = {}

    for short_type, generator in [
        ("hook", generate_hook),
        ("dry_run", generate_dry_run),
        ("code", generate_code_reveal),
        ("dialogue", generate_dialogue),
    ]:
        print(f"  [shorts] Generating {short_type}...")
        script = generator(question, part)
        path = os.path.join(output_dir, f"short_{short_type}.py")
        with open(path, "w") as f:
            f.write(script)
        paths[short_type] = path

    return paths


if __name__ == "__main__":
    q = {
        "slug": "two-sum", "title": "Two Sum", "category": "dsa",
        "pattern": "two_pointer", "difficulty": "easy",
        "companies": "google,amazon,meta",
        "dry_run": "nums=[2,7,11,15],target=9 → hash map → return [0,1]",
        "approach": "Hash map. O(n) time O(n) space.",
        "what_interviewers_want": "Recognize hash map over O(n²). Clarify constraints.",
        "python_code": "def twoSum(nums, target):\n    seen={}\n    for i,n in enumerate(nums):\n        if target-n in seen: return [seen[target-n],i]\n        seen[n]=i",
        "java_code": "public int[] twoSum(int[] nums, int target) { ... }",
    }
    part = {
        "part_number": 1, "total_parts": 1,
        "part_title": "Two Sum", "part_focus": "Hash map approach",
        "short_angles": {
            "hook": "Why O(n²) gets you rejected at Google",
            "dry_run": "Hash map lookup step by step",
            "code": "Optimal Python + Java solution",
            "dialogue": "Interviewer asks about time complexity",
        }
    }
    paths = generate_all_shorts(q, part, "output/shorts")
    print(json.dumps(paths, indent=2))
