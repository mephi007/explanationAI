"""
copy_writer.py — Gemini Flash generates raw copy, Claude Haiku reviews + rewrites.
Agent 3 rules are baked into both system prompts.
Outputs: LinkedIn carousel caption, 4 Instagram captions (one per short), YouTube metadata.
"""

import os
import re
import json
import anthropic
import google.generativeai as genai

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-1.5-flash"

# Claude Haiku for quality gate (~₹0.5/day)
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# ─── Agent 3 rules (injected into EVERY prompt) ───────────────────────────────
AGENT3 = """
YOU ARE AGENT 3 — World's best tech content strategist for FAANG interview prep.
Your audience: Indian engineers aged 22-32 preparing for MAANG/product companies.
They follow 50+ channels. You have 2 seconds to stop their scroll.

IRONCLAD RULES:
1. HOOK = First 2 lines. Must create FOMO or reveal a surprising failure. 
   NEVER start with: "Today we", "In this post", "Let's explore", "Here's".
   ALWAYS start with one of: personal failure, surprising statistic, contrarian claim, 
   direct challenge ("You're solving this wrong."), or company name drop.

2. COMPANY ANCHORING = Always name at least ONE specific company. Not "top companies" — 
   say "Google", "Meta", "Flipkart". Makes content feel like insider info.

3. THE TWIST = Every post must have "what most candidates miss" or "what the interviewer 
   is really testing". This is the viral hook — the gap between what people think and reality.

4. SPECIFICITY = Real numbers. Real companies. Real interview rounds (L4/SDE-2/Senior).
   Vague = skipped. Specific = saved.

5. CTA = Always end with exactly: "Follow for daily FAANG patterns."
   Nothing else. Not "like and subscribe". Not "share this post".

6. TONE = Senior peer sharing insider knowledge. NOT a tutorial channel.
   Write like a Principal Engineer sharing what they wish they knew.
"""

LINKEDIN_RULES = """
LinkedIn specific rules:
- Length: 1200-1500 characters exactly
- Line breaks every 2-3 lines maximum (LinkedIn readers hate walls of text)
- Max 3 emojis total — use them strategically, not decoratively
- 5 hashtags at the very end: #DSA #SystemDesign #SoftwareEngineering #MAANG #TechIndia
- Carousel context: Tell readers to swipe through the carousel for the visual walkthrough
- LinkedIn audience is senior (SDE-2, SDE-3) — don't talk down to them
"""

INSTAGRAM_RULES = """
Instagram short caption rules:
- First 125 characters (visible before "more"): MUST be the complete hook. Self-contained.
- Total length after hook: 5-8 punchy lines max
- End with: "Watch the full dry-run animation above 👆"
- Hashtag block (separate paragraph): 
  #DSA #LeetCode #FAANG #SWEIndia #TechInterviewIndia #CodingInterview #PlacementPrep 
  #MAANG #BangaloreTech + 3 topic-specific tags (e.g. #DynamicProgramming #TwoPointer)
- Emoji: max 5 total
"""


def _gemini_generate(system: str, prompt: str, max_tokens: int = 1024) -> str:
    model = genai.GenerativeModel(model_name=GEMINI_MODEL, system_instruction=system)
    resp = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(temperature=0.75, max_output_tokens=max_tokens)
    )
    return resp.text.strip()


def _claude_review(draft: str, platform: str, question: dict) -> str:
    """Claude Haiku reviews Gemini draft and improves quality."""
    if not claude:
        return draft  # No Claude key → use Gemini draft as-is

    prompt = f"""Review and improve this {platform} post for a DSA interview prep channel.

ORIGINAL DRAFT:
{draft}

CONTEXT:
- Question: {question.get('title','')}
- Companies: {question.get('companies','')}
- What interviewers want: {question.get('what_interviewers_want','')}

AGENT 3 RULES TO ENFORCE:
{AGENT3}

{LINKEDIN_RULES if platform == 'linkedin' else INSTAGRAM_RULES}

TASK:
1. Check if the hook follows the rules (no "Today we..." openers)
2. Verify company name is specific (not "top companies")
3. Ensure "what most candidates miss" insight is present
4. Tighten the copy — remove any filler words
5. Verify CTA is exactly: "Follow for daily FAANG patterns."

Return ONLY the improved post text. No commentary."""

    msg = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


def generate_linkedin_carousel_caption(question: dict, part: dict) -> str:
    companies = question.get("companies", "").split(",")
    top_co = companies[0].strip().title() if companies else "Google"
    pattern = question.get("pattern", "").replace("_", " ").title()

    prompt = f"""Write a LinkedIn carousel caption for this {'Part ' + str(part['part_number']) + '/' + str(part['total_parts']) + ' of ' if part['total_parts'] > 1 else ''}{question['title']} carousel.

Question: {question['title']}
Part focus: {part.get('part_focus', question.get('description',''))}
Primary company: {top_co}
Pattern: {pattern}
Difficulty: {question.get('difficulty','medium').upper()}
What interviewers really want: {question.get('what_interviewers_want','')}
Dry run insight: {question.get('dry_run','')[:200]}

FORMAT (follow exactly):
[2-line hook with {top_co} failure angle]

[Blank line]
[3-4 lines: why this matters — what most candidates do wrong]

[Blank line]  
👉 Swipe through the 10 slides for the complete visual walkthrough.

[Blank line]
[2 lines: key insight from this question — what the interviewer is really testing]

[Blank line]
Time: [complexity]
Space: [complexity]

[Blank line]
Follow for daily FAANG patterns.

#DSA #SystemDesign #SoftwareEngineering #MAANG #TechIndia"""

    draft = _gemini_generate(AGENT3 + "\n" + LINKEDIN_RULES, prompt)
    return _claude_review(draft, "linkedin", question)


def generate_instagram_caption(question: dict, part: dict, short_type: str) -> str:
    """
    short_type: 'hook' | 'dry_run' | 'code' | 'dialogue'
    Each short gets its own caption tuned to that content.
    """
    companies = question.get("companies", "").split(",")
    top_co = companies[0].strip().title() if companies else "Google"
    angle = part["short_angles"].get(short_type, "")

    caption_focus = {
        "hook": f"The failure angle — why most candidates get rejected on this at {top_co}",
        "dry_run": f"The dry-run animation — every step of the {question.get('pattern','').replace('_',' ')} approach",
        "code": f"The actual Python + Java code — clean, concise, interview-ready",
        "dialogue": f"How to handle this exact question in a {top_co} interview",
    }.get(short_type, angle)

    prompt = f"""Write an Instagram caption for the '{short_type}' short about: {question['title']}

Short content: {caption_focus}
Company: {top_co}
Part: {part['part_number']}/{part['total_parts']}
Interviewers want: {question.get('what_interviewers_want','')[:150]}

CRITICAL: First 125 chars must be a complete standalone hook — readers see ONLY this before "more".
Write it as if {top_co} is watching and this is the one thing every candidate needs to know."""

    draft = _gemini_generate(AGENT3 + "\n" + INSTAGRAM_RULES, prompt, max_tokens=512)
    return _claude_review(draft, "instagram", question)


def generate_youtube_metadata(question: dict, part: dict, video_type: str) -> dict:
    """video_type: 'short_hook' | 'short_dry_run' | 'short_code' | 'short_dialogue' | 'long'"""
    companies = question.get("companies", "").split(",")
    top_co = companies[0].strip().title() if companies else "Google"
    pattern = question.get("pattern", "").replace("_", " ").title()
    part_suffix = f" | Part {part['part_number']}" if part['total_parts'] > 1 else ""

    titles = {
        "short_hook":    f"{question['title']} — Why You'll Fail at {top_co}{part_suffix}",
        "short_dry_run": f"{question['title']} — {pattern} Animated{part_suffix} | {top_co} Interview",
        "short_code":    f"{question['title']} — Python + Java Solution{part_suffix} | O(n)",
        "short_dialogue":f"REAL {top_co} Interview: {question['title']}{part_suffix}",
        "long":          f"{question['title']} — Complete {top_co} Interview Guide | {pattern}{part_suffix}",
    }
    title = titles.get(video_type, f"{question['title']} | {top_co} Interview")[:100]

    tags_base = ["dsa", "leetcode", "faang", "coding interview", "system design",
                 "maang", "swe india", "placement prep", top_co.lower(),
                 pattern.lower(), question.get("difficulty", "medium"),
                 question.get("pattern", "").replace("_", " "),
                 question["title"].lower()[:30]]

    description = (
        f"{'🔴 LIVE INTERVIEW' if video_type == 'short_dialogue' else '📚 LEARN'}: {question['title']}\n\n"
        f"This {'short' if 'short' in video_type else 'video'} covers: {part.get('part_focus', question.get('description',''))[:200]}\n\n"
        f"Companies that ask this: {question.get('companies','').replace(',', ' · ').upper()}\n"
        f"Pattern: {pattern} | Difficulty: {question.get('difficulty','').upper()}\n\n"
        f"{'⏱ Timestamps\\n0:00 Problem setup\\n1:00 Dry run\\n2:30 Optimal approach\\n4:00 Code walkthrough\\n' if video_type == 'long' else ''}"
        f"Subscribe for daily FAANG patterns 👆"
    )[:5000]

    return {
        "title": title,
        "description": description,
        "tags": tags_base[:15],
        "category_id": "27",  # Education
    }


def generate_all_copy(question: dict, part: dict, output_dir: str) -> dict:
    """Generate all copy for today's content. Returns paths."""
    os.makedirs(output_dir, exist_ok=True)
    paths = {}

    print("[copy] LinkedIn carousel caption...")
    li = generate_linkedin_carousel_caption(question, part)
    li_path = os.path.join(output_dir, "linkedin_caption.txt")
    with open(li_path, "w") as f: f.write(li)
    paths["linkedin"] = li_path

    print("[copy] Instagram captions (4 shorts)...")
    ig_paths = {}
    for short_type in ["hook", "dry_run", "code", "dialogue"]:
        ig = generate_instagram_caption(question, part, short_type)
        p = os.path.join(output_dir, f"ig_{short_type}.txt")
        with open(p, "w") as f: f.write(ig)
        ig_paths[short_type] = p
    paths["instagram"] = ig_paths

    print("[copy] YouTube metadata (5 videos)...")
    yt_all = {}
    for vtype in ["short_hook", "short_dry_run", "short_code", "short_dialogue", "long"]:
        meta = generate_youtube_metadata(question, part, vtype)
        yt_all[vtype] = meta
    yt_path = os.path.join(output_dir, "youtube_metadata.json")
    with open(yt_path, "w") as f: json.dump(yt_all, f, indent=2)
    paths["youtube"] = yt_path

    print(f"[copy] All copy → {output_dir}/")
    return paths
