"""
video_renderer.py — Renders all 5 videos per day:
  - 4 shorts (portrait 9:16, <75s each)
  - 1 long-form (landscape 16:9, 10-15 min)

Pipeline per video:
  1. Generate voiceover text (Gemini)
  2. Synthesize voice (Kokoro TTS)
  3. Render Manim animation (manim CLI)
  4. Merge audio + video (FFmpeg)
  5. Generate thumbnail (Pillow, long-form only)

In production: GitHub Actions matrix runs all 5 in parallel.
"""

import os
import re
import subprocess
import numpy as np
from pathlib import Path
from datetime import datetime
import google.generativeai as genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

KOKORO_VOICE_A = os.environ.get("KOKORO_VOICE_A", "am_adam")      # interviewer / narrator
KOKORO_VOICE_B = os.environ.get("KOKORO_VOICE_B", "af_heart")     # candidate / secondary

try:
    from kokoro import KPipeline
    import soundfile as sf
    KOKORO_OK = True
except ImportError:
    KOKORO_OK = False
    print("[render] WARNING: kokoro not installed — TTS will be silent placeholder")

SAMPLE_RATE = 24000


# ── TTS helpers ──────────────────────────────────────────────────────────────

def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


def _synth(pipeline, text: str) -> np.ndarray:
    chunks = []
    for _, _, audio in pipeline(text, voice=KOKORO_VOICE_A):
        if audio is not None and len(audio) > 0:
            chunks.append(audio)
    return np.concatenate(chunks) if chunks else _silence(0.1)


def _synth_dialogue(text_a: str, text_b: str) -> np.ndarray:
    """Synthesize two-voice dialogue with voice switching."""
    if not KOKORO_OK:
        return _silence(30.0)

    pipe_a = KPipeline(lang_code="a")
    pipe_b = KPipeline(lang_code="a")

    parts = []
    # Alternate voices for dialogue
    for i, (voice, text) in enumerate([(KOKORO_VOICE_A, text_a), (KOKORO_VOICE_B, text_b)]):
        chunks = []
        pipe = pipe_a if i == 0 else pipe_b
        for _, _, audio in pipe(text, voice=voice):
            if audio is not None:
                chunks.append(audio)
        if chunks:
            parts.append(np.concatenate(chunks))
            parts.append(_silence(0.4))  # gap between speakers

    return np.concatenate(parts) if parts else _silence(10.0)


def generate_voiceover_text(question: dict, part: dict, short_type: str) -> str:
    """Use Gemini to write tight voiceover text for each short type."""
    if not GEMINI_API_KEY:
        return f"Today we're looking at {question['title']}. Let's dive in."

    prompts = {
        "hook": f"""Write a 55-second voiceover script for a hook short about {question['title']}.
Rules: Start with failure angle. Show wrong approach. End with "watch Short 2 for the approach."
No solution revealed. 120-140 words. Natural spoken English. Short sentences.
Topic: {part['short_angles']['hook']}
Company: {question.get('companies','').split(',')[0].title()}""",

        "dry_run": f"""Write a 70-second voiceover for a dry-run animation of {question['title']}.
Rules: No intro. Start narrating the animation immediately. One sentence per step.
Use: "Now we...", "Notice how...", "At this point..."
Insert [PAUSE 0.5] between steps. End with time/space complexity.
Dry run: {question.get('dry_run','')}
130-160 words.""",

        "code": f"""Write a 55-second voiceover for a code reveal short for {question['title']}.
Rules: Explain each line as it appears. Point out the key insight.
End with: "Time: O(?) Space: O(?). Code in the comments."
Code: {question.get('python_code','')[:300]}
110-130 words.""",

        "dialogue": f"""Write a 40-second TWO-VOICE dialogue script.
Format each line as:
INTERVIEWER: [text]
CANDIDATE: [text]

Rules: 8-10 lines total. Candidate first answer slightly wrong/incomplete.
Interviewer probes. Candidate recovers with optimal insight. Interviewer: "Exactly."
Topic: {part['short_angles']['dialogue']}
Keep each line under 20 words.""",
    }

    model = genai.GenerativeModel("gemini-1.5-flash")
    resp = model.generate_content(
        prompts.get(short_type, prompts["dry_run"]),
        generation_config=genai.GenerationConfig(temperature=0.5, max_output_tokens=512)
    )
    return resp.text.strip()


def synthesize_voice(voiceover_text: str, output_path: str,
                     is_dialogue: bool = False) -> str:
    """Convert voiceover text to WAV. Returns path."""
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    if not KOKORO_OK:
        # Write silent placeholder
        sf_available = False
        try:
            import soundfile as sf
            sf_available = True
        except Exception:
            pass
        silence = _silence(60.0)
        if sf_available:
            sf.write(output_path, silence, SAMPLE_RATE)
        return output_path

    import soundfile as sf

    if is_dialogue:
        # Parse INTERVIEWER: / CANDIDATE: lines
        lines = voiceover_text.strip().splitlines()
        audio_parts = []
        for line in lines:
            line = line.strip()
            if not line:
                audio_parts.append(_silence(0.3))
                continue
            if line.upper().startswith("INTERVIEWER:"):
                text = line.split(":", 1)[1].strip()
                pipe = KPipeline(lang_code="a")
                audio_parts.append(_synth(pipe, text))
                audio_parts.append(_silence(0.5))
            elif line.upper().startswith("CANDIDATE:"):
                text = line.split(":", 1)[1].strip()
                pipe = KPipeline(lang_code="a")
                chunks = []
                for _, _, audio in pipe(text, voice=KOKORO_VOICE_B):
                    if audio is not None: chunks.append(audio)
                if chunks:
                    audio_parts.append(np.concatenate(chunks))
                    audio_parts.append(_silence(0.5))
        final = np.concatenate(audio_parts) if audio_parts else _silence(30.0)
    else:
        # Standard single-voice with [PAUSE X] support
        pipe = KPipeline(lang_code="a")
        segments = re.split(r'\[PAUSE\s*([\d.]*)\]', voiceover_text, flags=re.IGNORECASE)
        audio_parts = []
        for i, seg in enumerate(segments):
            if i % 2 == 1:  # pause duration captured
                try:
                    audio_parts.append(_silence(float(seg) if seg else 0.4))
                except ValueError:
                    audio_parts.append(_silence(0.4))
            else:
                seg = seg.strip()
                if seg:
                    audio_parts.append(_synth(pipe, seg))
                    audio_parts.append(_silence(0.15))
        final = np.concatenate(audio_parts) if audio_parts else _silence(60.0)

    sf.write(output_path, final, SAMPLE_RATE)
    duration = len(final) / SAMPLE_RATE
    print(f"[tts] {os.path.basename(output_path)}: {duration:.1f}s")
    return output_path


def render_manim(script_path: str, class_name: str,
                 output_dir: str, quality: str = "m") -> str:
    """Run Manim renderer. Returns path to output MP4."""
    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        "manim",
        f"-q{quality}",
        "--fps", "30",
        "--output_file", f"{class_name}.mp4",
        "--media_dir", output_dir,
        script_path,
        class_name,
    ]

    print(f"[manim] Rendering {class_name} from {Path(script_path).name}...")
    result = subprocess.run(cmd, capture_output=True, text=True,
                            cwd=os.path.dirname(script_path) or ".")

    if result.returncode != 0:
        print(f"[manim] STDERR (last 2000 chars):\n{result.stderr[-2000:]}")
        raise RuntimeError(f"Manim render failed (exit {result.returncode})")

    # Find the rendered file
    for root, _, files in os.walk(output_dir):
        for f in files:
            if f.endswith(".mp4") and class_name in f:
                return os.path.join(root, f)
    # Fallback: any mp4
    for root, _, files in os.walk(output_dir):
        for f in files:
            if f.endswith(".mp4"):
                return os.path.join(root, f)

    raise FileNotFoundError(f"No MP4 found in {output_dir} after Manim render")


def merge_audio_video(video_path: str, audio_path: str,
                      output_path: str, loop_video: bool = False) -> str:
    """FFmpeg merge. If audio longer than video, freezes last frame."""
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    if loop_video:
        # Loop video to match audio length
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", video_path,
            "-i", audio_path,
            "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart",
            output_path,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ffmpeg] STDERR: {result.stderr[-500:]}")
        raise RuntimeError(f"FFmpeg merge failed")

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"[ffmpeg] {Path(output_path).name}: {size_mb:.1f}MB")
    return output_path


def crop_to_portrait(landscape_path: str, portrait_path: str) -> str:
    """Crop 16:9 to 9:16 by taking center 1080px width."""
    cmd = [
        "ffmpeg", "-y", "-i", landscape_path,
        "-vf", "scale=-1:1920,crop=1080:1920",
        "-c:v", "libx264", "-c:a", "copy",
        "-movflags", "+faststart", portrait_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ffmpeg] Portrait crop failed: {result.stderr[-200:]}")
        return landscape_path  # fallback
    return portrait_path


def generate_thumbnail(question: dict, part: dict, output_path: str) -> str:
    """Pillow thumbnail for long-form video."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import textwrap

        W, H = 1280, 720
        img = Image.new("RGB", (W, H), (10, 14, 28))
        draw = ImageDraw.Draw(img)

        # Accent bars
        draw.rectangle([0, 0, 10, H], fill=(99, 102, 241))
        draw.rectangle([0, H - 10, W, H], fill=(236, 72, 153))

        def font(size, bold=False):
            paths = [
                f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'Bold' if bold else ''}.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ]
            for p in paths:
                if os.path.exists(p):
                    try: return ImageFont.truetype(p, size)
                    except: pass
            return ImageFont.load_default()

        # Company tags
        companies = [c.strip().upper() for c in question.get("companies","").split(",")][:3]
        x = 40
        for c in companies:
            draw.rectangle([x, 40, x + len(c)*13 + 20, 75], fill=(99, 102, 241))
            draw.text((x+10, 47), c, font=font(20, True), fill=(248, 250, 252))
            x += len(c)*13 + 35

        # Difficulty badge
        diff = question.get("difficulty","medium").upper()
        diff_colors = {"EASY": (34,197,94), "MEDIUM": (250,204,21), "HARD": (239,68,68)}
        draw.rectangle([x, 40, x + 90, 75], fill=diff_colors.get(diff, (148,163,184)))
        draw.text((x+10, 47), diff, font=font(20, True), fill=(10,14,28))

        # Title
        title = part.get("part_title") or question.get("title", "")
        lines = textwrap.wrap(title, width=20)
        y = 110
        for line in lines[:3]:
            draw.text((40, y), line, font=font(72, True), fill=(248, 250, 252))
            y += 84

        # Part badge
        if part.get("total_parts", 1) > 1:
            pt = f"Part {part['part_number']} of {part['total_parts']}"
            draw.text((40, y + 10), pt, font=font(36), fill=(236, 72, 153))

        # Pattern
        pattern = question.get("pattern","").replace("_"," ").title()
        draw.text((40, H - 80), f"Pattern: {pattern}", font=font(32), fill=(148, 163, 184))

        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        img.save(output_path, "JPEG", quality=92)
        print(f"[thumb] Saved: {output_path}")
        return output_path

    except Exception as e:
        print(f"[thumb] Failed: {e}")
        return ""


def render_all(question: dict, part: dict, short_scripts: dict,
               longform_script: str, output_dir: str) -> dict:
    """
    Render all 5 videos. Returns dict of output paths.
    In production this is parallelized via GitHub Actions matrix.
    """
    paths = {}

    # ── 4 Shorts ──────────────────────────────────────────────────────
    for short_type, script_path in short_scripts.items():
        print(f"\n[render] === Short: {short_type} ===")
        render_dir = os.path.join(output_dir, "render", f"short_{short_type}")
        audio_dir = os.path.join(output_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)

        # 1. Voiceover
        vo_text = generate_voiceover_text(question, part, short_type)
        vo_path = os.path.join(audio_dir, f"voice_{short_type}.txt")
        with open(vo_path, "w") as f:
            f.write(vo_text)

        wav_path = os.path.join(audio_dir, f"voice_{short_type}.wav")
        synthesize_voice(vo_text, wav_path, is_dialogue=(short_type == "dialogue"))

        # 2. Render Manim
        try:
            anim_path = render_manim(script_path, "MainScene", render_dir, quality="m")
        except Exception as e:
            print(f"[render] Manim failed for {short_type}: {e}")
            paths[f"short_{short_type}_portrait"] = ""
            continue

        # 3. Merge
        merged_landscape = os.path.join(output_dir, f"short_{short_type}_landscape.mp4")
        merge_audio_video(anim_path, wav_path, merged_landscape)

        # 4. Portrait crop
        portrait_path = os.path.join(output_dir, f"short_{short_type}_portrait.mp4")
        crop_to_portrait(merged_landscape, portrait_path)
        paths[f"short_{short_type}_portrait"] = portrait_path

    # ── Long-form ──────────────────────────────────────────────────────
    print(f"\n[render] === Long-form ===")
    lf_render_dir = os.path.join(output_dir, "render", "longform")

    # Voiceover for long-form is embedded in Manim script narration
    # We synthesize a companion audio track
    lf_vo = f"""Welcome to today's deep dive on {question['title']}.
{part['part_focus']}
This is asked at {question.get('companies','').replace(',',', ')}.
Let's break it down completely — brute force, optimal approach, clean code, and the follow-up questions
that separate candidates who truly understand the pattern."""

    lf_wav = os.path.join(output_dir, "audio", "voice_longform_intro.wav")
    synthesize_voice(lf_vo, lf_wav)

    try:
        lf_anim = render_manim(longform_script, "LongFormScene", lf_render_dir, quality="h")
        lf_final = os.path.join(output_dir, "longform.mp4")
        merge_audio_video(lf_anim, lf_wav, lf_final, loop_video=False)
        paths["long"] = lf_final

        # Thumbnail
        thumb = generate_thumbnail(question, part,
                                   os.path.join(output_dir, "thumbnail.jpg"))
        paths["thumbnail"] = thumb

    except Exception as e:
        print(f"[render] Long-form render failed: {e}")
        paths["long"] = ""
        paths["thumbnail"] = ""

    print(f"\n[render] Complete. Videos: {[k for k,v in paths.items() if v]}")
    return paths


if __name__ == "__main__":
    # Test TTS only
    sample_vo = "Today we look at Two Sum. Most candidates get this wrong at Google. [PAUSE 0.5] Here's why."
    synthesize_voice(sample_vo, "/tmp/test_voice.wav")
    print("TTS test complete")
