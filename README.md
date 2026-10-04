# Whyzo Films

Hands-off pipeline for **Whyzo Films**, a YouTube Shorts channel of ~30-second, AI-animated, 3D-style curiosity
videos: how things work, why things are the way they are, what happens if, what to do if, true stories, strange
creatures and clever hacks. It runs on **GitHub Actions** (free for public repos) and you steer it from **Telegram**.

```
Every 6 hours (11:17pm, 5:17am, 11:17am, 5:17pm New York)
   ─► top Shorts in the niche this week + Google Trends ─► blocklist + AI filter
   ─► Telegram: "Whyzo Films: next 4 ideas"  [🎬1] [🎬2] [🎬3] [🎬4] [⏭ Skip]
You tap ideas (or ignore it: after 30 min it makes the top 2 itself)
   ─► AI writes an original 6-8 shot script ─► Wikipedia fact-check + AI safety review
   ─► one narrator voice ─► 3D-style AI stills (FLUX) ─► 3 key shots animated (fal.ai image-to-video)
   ─► camera moves on the other shots, word-by-word captions, whoosh sound effects, light music ─► 1080×1920 MP4
   ─► preview in Telegram [✅ Publish] [🔁 Redo] [🎙 New voice] [⏭ Skip]
You tap Publish (or ignore it: after 45 min it publishes itself)
   ─► YouTube (scheduled for the run's two publish slots, added to its series playlist) + optional Instagram / Facebook / TikTok
```

Publish slots (US Eastern, 2 every 6 hours): **1:30 & 3:00 AM, 7:30 & 9:00 AM, 1:30 & 3:00 PM, 7:30 & 9:00 PM**.

## What it costs

| Part | Service | Cost |
|---|---|---|
| Server / scheduler | GitHub Actions (public repo) | free |
| Scripts, review, titles | Gemini + free backups (Groq, Cerebras, Mistral, OpenRouter) | free |
| Voice | Microsoft Edge neural TTS (one fixed narrator) | free |
| 3D stills | fal.ai FLUX schnell (Cloudflare FLUX is the free fallback) | a few cents a day |
| **Animated shots** | **fal.ai image-to-video** (`ANIMATE_SHOTS` per video) | **the main cost; set a monthly cap at fal.ai** |
| Editing | FFmpeg | free |

Set `ANIMATE_SHOTS=0` to run completely free (stills with camera moves only). Check the current price of the
image-to-video model on its fal.ai page before raising `ANIMATE_SHOTS`.

---

## Setup (one time)

### 1. Telegram
Whyzo needs its **own bot**: a bot can only be read by one repo, so sharing Zorbly's would make the two
channels steal each other's replies.
1. In Telegram message **@BotFather** → `/newbot` → name it e.g. "Whyzo Films Bot". Copy the token → `TELEGRAM_BOT_TOKEN`.
2. Send your new bot any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates`. The number at
   `"chat":{"id":...}` is `TELEGRAM_CHAT_ID`.

### 2. AI keys
Reuse the same `GEMINI_API_KEY` (and optional `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `MISTRAL_API_KEY`,
`OPENROUTER_API_KEY`) as Zorbly. Run the workflow with command `aicheck` to test them.

### 3. fal.ai (animated shots)
1. Sign up at https://fal.ai, add credit, and **set a monthly spending limit** in billing.
2. Create an API key → secret `FAL_KEY`.
3. Optional Variables: `ANIMATE_SHOTS` (default `3`), `FAL_VIDEO_MODEL` (`wan` default, `kling`, or any fal
   image-to-video endpoint id).

### 4. YouTube channel + its own Google Cloud project
1. Create the **Whyzo Films** channel (YouTube → Settings → Add or manage channels → Create a channel; this makes a
   Brand Account). Add a profile picture, banner and the bio line "AI-animated facts & stories".
2. Verify the channel for custom thumbnails: https://www.youtube.com/verify
3. At https://console.cloud.google.com create a **new project** "Whyzo Films", enable **YouTube Data API v3**.
   A separate project gives Whyzo its own 10,000-unit daily quota, separate from Zorbly.
4. Credentials → **API key** → `YOUTUBE_API_KEY`.
5. OAuth consent screen: External, add yourself, then **Publish app / In production** (otherwise the token
   expires every 7 days). Home page / privacy / terms links:
   `https://akachwaha27.github.io/whyzo-films-autopilot/`, `.../privacy.html`, `.../terms.html`
   (turn on GitHub Pages: repo **Settings → Pages → Deploy from branch → main → /docs**).
6. Credentials → **OAuth client ID** → Desktop app → download as `client_secret.json` next to
   `tools/get_youtube_token.py`, then run `python get_youtube_token.py`. **Sign in and choose the Whyzo Films
   channel** when Google asks which account/channel. It prints `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
7. Uploads stay **private** until this project passes Google's API audit. Submit it at
   https://support.google.com/youtube/contact/yt_api_form (same way as Zorbly) and **ask for a quota increase to
   20,000 units/day** in the same form, because 8 uploads/day need about 17,000 units.
   - Until approved: Variable `YT_PRIVACY=private`, and the bot uploads at most 4 a day (`YT_DAILY_UPLOADS=4`).
   - After approval: `YT_PRIVACY=public`, `YT_DAILY_UPLOADS=8`.

### 5. Instagram / Facebook / TikTok (optional)
Same steps as Zorbly, with **new accounts for Whyzo** (Facebook Page + Instagram Creator account; TikTok account):
`tools/get_meta_token.py` → `FB_PAGE_ID`, `FB_PAGE_TOKEN`, `IG_USER_ID`; `tools/get_tiktok_token.py` (redirect URI
`https://akachwaha27.github.io/whyzo-films-autopilot/callback.html`) → `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`,
`TIKTOK_REFRESH_TOKEN`. Leave any of them blank to skip that platform.

### 6. Add everything to GitHub
Repo → **Settings → Secrets and variables → Actions**.

**Secrets:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY` (+ optional backups), `YOUTUBE_API_KEY`,
`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, `FAL_KEY`, optional `CF_ACCOUNT_ID` + `CF_API_TOKEN` (free
fallback images), optional `PIXABAY_API_KEY` / `PEXELS_API_KEY` (last-resort stock), optional Meta/TikTok secrets.

**Variables** (all optional):

| Variable | Default | Meaning |
|---|---|---|
| `YT_PRIVACY` | `private` | `public` after the API audit passes |
| `YT_DAILY_UPLOADS` | `4` | `8` after Google raises your quota |
| `IDEAS_PER_RUN` | `4` | Ideas sent to Telegram every 6 hours |
| `VIDEOS_PER_RUN` | `2` | Made automatically if you don't pick |
| `MAX_VIDEOS_PER_DAY` | `8` | Hard daily cap |
| `ANIMATE_SHOTS` | `3` | Animated shots per video (`0` = free, stills only) |
| `FAL_VIDEO_MODEL` | `wan` | `wan`, `kling`, or a fal endpoint id |
| `ART_STYLE` | stylized 3D render… | The look added to every image prompt |
| `VOICE` | `en-US-AndrewMultilingualNeural` | The channel narrator |
| `SELECT_TIMEOUT_HOURS` | `0.5` | Wait for your pick |
| `REQUIRE_APPROVAL` | `true` | Send previews before publishing |
| `APPROVE_TIMEOUT_HOURS` | `0.75` | Auto-publish after this long (`0` = always wait for you) |
| `PUBLISH_SLOTS_WEEKDAY` / `_WEEKEND` | 8 slots above | Publish times (`PUBLISH_TZ`, default New York) |
| `TARGET_SECONDS` | `32` | Video length |
| `CHANNEL_HANDLE` | `@WhyzoFilms` | Used in the subscribe line of every description |
| `FACT_CHECK` | `true` | Check facts against Wikipedia before rendering |
| `SFX` | `true` | Whoosh on scene changes |

### 7. Test
**Actions → whyzo-autopilot → Run workflow**:
- `test` renders one sample video and sends it to Telegram (nothing is posted). `test survival` / `test creature` etc. picks a format.
- `trends` sends the next idea list right away.

## Formats

| | Format | Example | Pick letter |
|---|---|---|---|
| ⚙️ | howitworks | How Revolving Doors Save Energy | `h` |
| 🤔 | why | Why Pilots Dim The Cabin Lights For Landing | `w` |
| 🤯 | whatif | What Happens If You Fall Into Quicksand | `i` |
| 🛟 | survival | What To Do If You're Caught In A Rip Current | `s` |
| 📜 | truestory | well-documented, non-graphic true stories | `t` |
| 🦎 | creature | strange real animals and plants | `c` |
| 🛠️ | hack | clever, safe, useful tricks | `k` |

Pick with `1,3` or change a format with a letter: `2s` makes idea 2 a survival video.

## Telegram commands
Videos are numbered by run + idea: `b2` = run B (6am–noon UTC), idea 2.

| Reply | What happens |
|---|---|
| `publish` / `publish b2` | Upload for the next free slot (`publish now` posts immediately) |
| `change shorter` | Rewrite with your notes |
| `redo` | Brand-new version |
| `voice` | Same script, re-recorded, fresh visuals |
| `title New Title 🤔` | Change only the title |
| `info` | Description, tags, credits |
| `skip` | Throw it away |
| `/now` `/status` `/help` | Fresh ideas · recent videos · all commands |

## Staying monetizable
- Every video is an original script, original AI visuals and an AI voice; nothing is reused from other creators.
  The channel is inspired by the *genre* of animated-fact Shorts; it never copies another channel's videos,
  scripts, characters, name or branding.
- YouTube's altered/synthetic content label is set on every upload (`containsSyntheticMedia`), and every
  description says the visuals and voice are AI.
- The safety review blocks gore, graphic injuries, politics, real living people, movie/TV characters and brands,
  medical/financial advice, and survival advice that contradicts official guidance.
- 8 AI videos a day is the pattern YouTube's "inauthentic content" policy watches for. Start at 4 a day
  (`MAX_VIDEOS_PER_DAY=4`, `VIDEOS_PER_RUN=1`) for the first month, review previews, and step up when views and
  retention look healthy.

## PC folder
`tools/sync_library.py` copies videos, an Excel library and a dashboard to your PC (see the
`K:\Youtube Automation\Whyzo Films` folder's README).
