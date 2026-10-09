"""All settings come from environment variables (GitHub Secrets / Variables)."""
import os


def env(name, default=None, cast=str):
    val = os.getenv(name)
    if val is not None:
        val = val.strip().strip('"').strip("'").strip()  # pasted secrets often carry stray spaces/quotes/newlines
    if val is None or val == "":
        return default
    if cast is bool:
        return val.strip().lower() in ("1", "true", "yes", "on")
    return cast(val)


# --- Required secrets ---
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")          # your personal chat id
GEMINI_API_KEY = env("GEMINI_API_KEY")
YOUTUBE_API_KEY = env("YOUTUBE_API_KEY")             # for reading trends
PEXELS_API_KEY = env("PEXELS_API_KEY")               # free stock video/photos (optional)
PIXABAY_API_KEY = env("PIXABAY_API_KEY")             # free stock video/photos (optional)

# --- Publishing (any you leave blank is skipped) ---
YT_CLIENT_ID = env("YT_CLIENT_ID")
YT_CLIENT_SECRET = env("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = env("YT_REFRESH_TOKEN")
YT_PRIVACY = env("YT_PRIVACY", "private")            # set Variable YT_PRIVACY=public after Google approves your API audit

FB_PAGE_ID = env("FB_PAGE_ID")                       # Facebook Page that gets the Reels
FB_PAGE_TOKEN = env("FB_PAGE_TOKEN")                 # Page token from tools/get_meta_token.py (doesn't expire)
IG_USER_ID = env("IG_USER_ID")
IG_ACCESS_TOKEN = env("IG_ACCESS_TOKEN") or FB_PAGE_TOKEN  # the same Page token works for Instagram
IG_GRAPH_HOST = env("IG_GRAPH_HOST", "graph.facebook.com")
IG_API_VERSION = env("IG_API_VERSION", "v23.0")

TIKTOK_ACCESS_TOKEN = env("TIKTOK_ACCESS_TOKEN")
TIKTOK_REFRESH_TOKEN = env("TIKTOK_REFRESH_TOKEN")
TIKTOK_CLIENT_KEY = env("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = env("TIKTOK_CLIENT_SECRET")
# draft = video lands in your TikTok inbox; you add a trending sound and tap Post (works without TikTok's audit).
# direct = posts straight to your profile (until TikTok audits the app this is private-only, SELF_ONLY).
TIKTOK_MODE = env("TIKTOK_MODE", "draft")
TIKTOK_PRIVACY = env("TIKTOK_PRIVACY", "SELF_ONLY")  # direct mode only; unaudited apps may only post SELF_ONLY
INSTAGRAM_HASHTAGS = env("INSTAGRAM_HASHTAGS", 5, int)  # Instagram allows at most 5 hashtags per post

# --- AI visuals ---
CHANNEL_NAME = env("CHANNEL_NAME", "Whyzo Films")
CHANNEL_HANDLE = env("CHANNEL_HANDLE", "@WhyzoFilms")
CF_ACCOUNT_ID = env("CF_ACCOUNT_ID")                 # free FLUX stills (fallback when FAL_KEY is not set)
CF_API_TOKEN = env("CF_API_TOKEN")
FAL_KEY = env("FAL_KEY")                             # fal.ai: sharp 9:16 stills + image-to-video animation
FAL_IMAGE_MODEL = env("FAL_IMAGE_MODEL", "fal-ai/flux/schnell")
FAL_VIDEO_MODEL = env("FAL_VIDEO_MODEL", "wan")      # wan | kling | any fal image-to-video endpoint id
ANIMATE_SHOTS = env("ANIMATE_SHOTS", 3, int)         # animated (moving) shots per video; 0 = stills with camera moves only
# One fixed look so every video feels like the same channel
ART_STYLE = env("ART_STYLE", "stylized realistic 3D animation render, smooth clay-like CGI skin, soft studio lighting, "
                "shallow depth of field, clean simple background, vibrant but natural colors, cinematic, "
                "vertical 9:16 composition, no text, no logos, no watermark")
SFX = env("SFX", True, bool)                         # soft whoosh on every scene change

# --- Behaviour (GitHub Variables) ---
NICHE = env("NICHE", "curious facts told as short 3D-animated scenes: how things work, why things are the way they are, "
            "what would happen if, survival know-how, odd history and true stories, strange animals, clever inventions")
REGION = env("REGION", "US")
LANGUAGE = env("LANGUAGE", "en")
GEMINI_MODEL = env("GEMINI_MODEL")                      # blank = auto-pick newest free Flash model
VOICE = env("VOICE", "en-US-AndrewMultilingualNeural")  # the channel narrator (one consistent voice)
VOICES = env("VOICES", VOICE)                        # comma-separated pool; default = the single narrator voice
VISUALS = env("VISUALS", "ai")                       # ai (3D look, recommended) | mixed | stock
TOPICS_PER_DAY = env("IDEAS_PER_RUN", 4, int)        # ideas sent to Telegram every run (every 6 hours)
RANKINGS_PER_DAY = 0
MAX_VIDEOS_PER_DAY = env("MAX_VIDEOS_PER_DAY", 8, int)
AUTO_PICK_COUNT = env("VIDEOS_PER_RUN", 2, int)      # made every run if you don't pick
SELECT_TIMEOUT_HOURS = env("SELECT_TIMEOUT_HOURS", 0.5, float)
REQUIRE_APPROVAL = env("REQUIRE_APPROVAL", True, bool)
APPROVE_TIMEOUT_HOURS = env("APPROVE_TIMEOUT_HOURS", 0.75, float)  # auto-publish if you stay silent
TARGET_SECONDS = env("TARGET_SECONDS", 32, int)
FACT_CHECK = env("FACT_CHECK", True, bool)           # check script facts against Wikipedia before rendering (set var FACT_CHECK=true to enable)
POLL_MINUTES = env("POLL_MINUTES", 12, float)        # how long each run stays online answering Telegram
# Peak Shorts viewing slots (local time of your audience). Each approved video takes the next free slot.
SCHEDULE_PUBLISH = env("SCHEDULE_PUBLISH", True, bool)
PUBLISH_TZ = env("PUBLISH_TZ", "America/New_York")
# 2 videos every 6 hours (idea runs fire ~11:17pm/5:17am/11:17am/5:17pm ET; videos are approved ~1.5-2h later)
PUBLISH_SLOTS_WEEKDAY = env("PUBLISH_SLOTS_WEEKDAY", "01:30,03:00,07:30,09:00,13:30,15:00,19:30,21:00")
PUBLISH_SLOTS_WEEKEND = env("PUBLISH_SLOTS_WEEKEND", PUBLISH_SLOTS_WEEKDAY)
YT_DAILY_UPLOADS = env("YT_DAILY_UPLOADS", 4, int)   # ~2,100 quota units each; free quota is 10,000/day -> raise to 8 after Google grants more quota
KEEP_VIDEOS_DAYS = env("KEEP_VIDEOS_DAYS", 30, int)  # delete stored video files older than this (your PC sync keeps copies)
STATS_EVERY_HOURS = env("STATS_EVERY_HOURS", 2, float)  # refresh YouTube views/likes/comments for the dashboard
LIBRARY_DIR = env("LIBRARY_DIR", "archive")  # permanent archive of every video + every daily idea list

WIDTH, HEIGHT, FPS = 1080, 1920, 30
STATE_FILE = env("STATE_FILE", "state/state.json")
WORK_DIR = env("WORK_DIR", "work")
GITHUB_REPOSITORY = env("GITHUB_REPOSITORY")         # set automatically in Actions
