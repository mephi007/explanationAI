# DSA Content Engine v2 🚀

> **10 pieces of content per day. Fully automated. ₹0/month.**
> 4 Shorts/Reels + 1 long-form YouTube + 1 LinkedIn carousel.
> AI-generated animations, dual-voice TTS, Telegram preview gate, staggered posting.

---

## What it produces daily

| Time (IST) | Platform | Content |
|---|---|---|
| 6:00 AM | YouTube | Long-form (10-15 min) deep dive |
| 7:00 AM | YouTube + Instagram | Short 1 — Hook (60s FOMO bait) |
| 8:00 AM | LinkedIn | 10-slide carousel (PDF) |
| 12:30 PM | YouTube + Instagram | Short 2 — Dry run animation (75s) |
| 5:30 PM | YouTube + Instagram | Short 3 — Code reveal (60s) |
| 9:00 PM | YouTube + Instagram | Short 4 — Interview dialogue (45s) |

---

## Architecture

```
Every Sunday: calendar_planner.py plans next 7 days
              → series_planner.py splits deep topics across days
              → Telegram preview of weekly plan

Every day at 6 AM IST:
  Intelligence layer:
    ├── Load today's calendar entry (SQLite)
    ├── Determine part (shallow = 1 part, deep = series)
    └── Get part plan (series_planner.py)

  Generation layer (Gemini Flash):
    ├── 4 short Manim scripts (hook/dry_run/code/dialogue)
    ├── 1 long-form Manim script (10-15 min, chaptered)
    ├── Voiceover scripts for each video
    ├── LinkedIn carousel caption
    ├── 4 Instagram captions (one per short)
    └── YouTube metadata (title/description/tags × 5)

  Render layer:
    ├── Kokoro TTS → WAV audio (dual-voice for dialogue)
    ├── Manim → MP4 animations (portrait + landscape)
    ├── FFmpeg → merge audio + video
    └── Pillow → 10-slide carousel PDF + thumbnail

  Quality gate:
    └── Telegram bot → you review 4 shorts + carousel → approve/regen/skip

  Posting layer (staggered, 6 separate cron jobs):
    ├── LinkedIn API v2 → carousel Document post
    ├── Meta Graph API → 4 Instagram Reels
    └── YouTube Data API v3 → 4 Shorts + 1 long-form

  State management:
    └── state.db (SQLite, committed to repo) → dedup + calendar + retry queue
```

---

## GitHub Secrets Required

Go to: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | How to get | Required |
|---|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) → API Keys | ✅ Core |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys | ✅ Copy quality |
| `TELEGRAM_BOT_TOKEN` | @BotFather → /newbot | ✅ Preview gate |
| `TELEGRAM_CHAT_ID` | Run setup script | ✅ Preview gate |
| `LINKEDIN_ACCESS_TOKEN` | Run setup script | For LinkedIn |
| `LINKEDIN_PERSON_URN` | Run setup script | For LinkedIn |
| `INSTAGRAM_ACCESS_TOKEN` | Run setup script | For Instagram |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Run setup script | For Instagram |
| `YOUTUBE_CLIENT_ID` | Google Cloud Console | For YouTube |
| `YOUTUBE_CLIENT_SECRET` | Google Cloud Console | For YouTube |
| `YOUTUBE_REFRESH_TOKEN` | Run setup script | For YouTube |

> Pipeline skips platforms with missing credentials. Start with just `GEMINI_API_KEY` + Telegram to test content quality.

---

## Setup (30 minutes)

### Step 1 — Fork and clone
```bash
git clone https://github.com/YOUR_USERNAME/dsa-content-engine
cd dsa-content-engine
```

### Step 2 — Get Gemini API key (free)
1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Click "Get API Key" → Create
3. Free tier: 1,500 requests/day — more than enough

### Step 3 — Set up credentials (one-time)
```bash
pip install requests
python scripts/setup_credentials.py --all
```
Follow the prompts for each platform. Copy secrets to GitHub.

### Step 4 — First dry run
Go to Actions → "Daily Content Pipeline v2" → Run workflow → set `dry_run=true`

Check the artifact download: LinkedIn caption, Instagram captions, YouTube metadata, thumbnail.

### Step 5 — Review first live run
Next morning at 6 AM IST, you'll receive a Telegram message with 4 videos + carousel.
Tap "✅ Approve All" — content posts throughout the day.

---

## Series logic

Questions with `depth_score >= 7` are automatically split across consecutive days:

```
Monday:    "Dynamic Programming — Intuition & Brute Force"   (Part 1/3)
Tuesday:   "Dynamic Programming — Optimal + Tabulation"      (Part 2/3)
Wednesday: "Dynamic Programming — Variations & Follow-ups"   (Part 3/3)
```

Each part gets its own 4 shorts + long-form + carousel. The calendar planner schedules
all parts in advance so there are no gaps.

---

## Content schedule

| Day | Category | Difficulty target |
|---|---|---|
| Monday | DSA | Easy (entry point, high discovery) |
| Tuesday | DSA | Medium |
| Wednesday | System Design | Any |
| Thursday | DSA | Medium |
| Friday | DSA | Hard |
| Saturday | LLD | Medium |
| Sunday | System Design | Any |

---

## Question bank (46 questions, grows automatically)

**DSA (29):** Two Sum, 3Sum, Container With Most Water, Sliding Window Maximum,
Minimum Window Substring, Binary Search, Search in Rotated Array, Koko Eating Bananas,
Climbing Stairs, LCS, Edit Distance, Coin Change, Word Break, LIS, 0/1 Knapsack,
Number of Islands, Course Schedule, Word Ladder, Dijkstra, Validate BST, LCA,
Serialize Binary Tree, Kth Largest, Merge K Lists, Daily Temperatures,
Largest Rectangle, Reverse Linked List, LRU Cache, Sliding Window Maximum

**System Design (8):** URL Shortener, Rate Limiter, Instagram Feed, WhatsApp, YouTube,
Notification System, Distributed Cache, Search Autocomplete

**LLD (4):** Parking Lot, Elevator, Splitwise, Chess

**CS Fundamentals (5):** Process vs Thread, Virtual Memory, ACID Transactions,
Database Indexing, HTTP vs HTTPS

### Adding questions
Edit `QUESTIONS` list in `src/question_bank.py`. Run `python src/question_bank.py` to rebuild bank.

Question format:
```python
{
    "slug": "unique-slug",
    "title": "Human Title",
    "category": "dsa",              # dsa | system_design | lld | cs_fundamentals
    "pattern": "two_pointer",       # see PATTERN_WEIGHT in question_bank.py
    "difficulty": "medium",         # easy | medium | hard
    "companies": "google,amazon",
    "depth_score": 5,               # 1-6: single day; 7-10: multi-part series
    "description": "...",
    "dry_run": "...",
    "approach": "...",
    "what_interviewers_want": "...",
    "python_code": "def ...",
    "java_code": "public ...",
}
```

---

## Telegram commands

Once the bot is running, these commands work in your Telegram chat:

| Command | Effect |
|---|---|
| `/skip` | Skip today's posting |
| `/regen_copy` | Regenerate all captions |
| `/regen_hook` | Regenerate hook short script |
| `/regen_all` | Regenerate everything |
| `/stats` | Show bank stats (total/posted/remaining) |
| `/preview` | Show today's question details |

---

## Monetization ladder

| Phase | When | Revenue stream |
|---|---|---|
| Foundation | 0–3 months | Zero. Post daily. Build trust. |
| First income | 3–6 months | YouTube monetization (1k subs + 4k watch hours). ₹199 PDF on Gumroad. |
| Consulting | 6–12 months | ₹5k–15k/month mock interviews on Topmate. LinkedIn sponsor slots. |
| Product | 12 months+ | ₹999–₹2999 cohort course. This channel is the top-of-funnel. |

---

## Cost breakdown

| Service | Cost |
|---|---|
| GitHub Actions | Free (2000 min/month — enough for 6 jobs/day) |
| Gemini Flash API | Free (1500 req/day) |
| Claude Haiku (copy review) | ~₹0.50/day at current pricing |
| Kokoro TTS | Free (Apache 2.0, runs in Actions) |
| Manim | Free (MIT) |
| LinkedIn API | Free |
| Meta Graph API | Free |
| YouTube Data API v3 | Free (10k units/day) |
| **Total** | **~₹15/month** |

When earning: upgrade Kokoro → ElevenLabs (~₹800/month) for significantly better voice quality.
