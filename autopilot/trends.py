"""Collect trending signals and turn them into Whyzo Films video ideas (every 6 hours)."""
import re
import xml.etree.ElementTree as ET
from datetime import timedelta

import requests

from . import config, llm, state

# Hard filter: anything matching these never reaches the AI or you.
BLOCKLIST = re.compile(r"\b(" + "|".join([
    # politics / government
    "election", "elect", "vote", "voter", "ballot", "president", "senator", "congress", "parliament",
    "democrat", "republican", "gop", "trump", "biden", "harris", "vance", "modi", "putin", "zelensky",
    "netanyahu", "minister", "governor", "mayor", "campaign", "impeach", "tariff", "policy", "protest",
    "immigration", "border", "deport", "supreme court", "lawsuit", "sued", "indict", "trial", "verdict",
    # conflict / violence / tragedy
    "war", "attack", "shooting", "shooter", "gun", "killed", "kill", "dead", "death", "dies", "died",
    "murder", "stabbing", "terror", "missile", "hostage", "gaza", "israel", "ukraine", "russia",
    "iran", "hamas", "victim", "funeral", "obituary", "arrest", "police", "jail", "crime", "scandal",
    # sensitive / divisive
    "abortion", "religion", "church", "mosque", "islam", "christian", "jewish", "gay", "trans",
    "racist", "racism", "lgbt", "vaccine", "covid", "cancer", "overdose", "suicide", "drug",
    "nsfw", "onlyfans", "leak", "nude", "affair", "divorce", "cheating", "feud", "beef", "diss",
    "bitcoin", "crypto", "stock", "lottery", "betting", "casino",
]) + r")\b", re.I)


def google_trends():
    url = f"https://trends.google.com/trending/rss?geo={config.REGION}"
    ns = {"ht": "https://trends.google.com/trending/rss"}
    out = []
    try:
        root = ET.fromstring(requests.get(url, timeout=30).content)
        for item in root.iter("item"):
            title = item.findtext("title", "")
            traffic = item.findtext("ht:approx_traffic", "", ns)
            news = [n.findtext("ht:news_item_title", "", ns) for n in item.findall("ht:news_item", ns)]
            out.append({"source": "Google Trends", "title": title, "signal": traffic,
                        "context": " | ".join(news[:2])})
    except Exception as e:  # noqa: BLE001
        print("Google Trends failed:", e)
    return out


def youtube_trending():
    if not config.YOUTUBE_API_KEY:
        return []
    out = []
    base = "https://www.googleapis.com/youtube/v3"
    try:
        r = requests.get(f"{base}/videos", timeout=30, params={
            "part": "snippet,statistics", "chart": "mostPopular", "regionCode": config.REGION,
            "maxResults": 50, "key": config.YOUTUBE_API_KEY}).json()
        for v in r.get("items", []):
            s = v["snippet"]
            out.append({"source": "YouTube Trending", "title": s["title"],
                        "signal": f'{int(v["statistics"].get("viewCount", 0)):,} views',
                        "context": " ".join(s.get("tags", [])[:6])})
        # Short-form signal: most-viewed Shorts from the last 48h (covers TikTok/Reels-style trends)
        after = (state.now() - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = requests.get(f"{base}/search", timeout=30, params={
            "part": "snippet", "q": "#shorts", "type": "video", "videoDuration": "short",
            "order": "viewCount", "publishedAfter": after, "regionCode": config.REGION,
            "relevanceLanguage": config.LANGUAGE, "maxResults": 50, "key": config.YOUTUBE_API_KEY}).json()
        for v in r.get("items", []):
            out.append({"source": "YouTube Shorts (48h)", "title": v["snippet"]["title"],
                        "signal": "top viewed short", "context": v["snippet"].get("description", "")[:120]})
    except Exception as e:  # noqa: BLE001
        print("YouTube trends failed:", e)
    return out


NICHE_QUERIES = ["how does it work", "why do", "what happens if", "what to do if", "true story animation",
                 "weird animal facts", "how it's made animation", "3d animation facts"]


def niche_shorts():
    """Most-viewed recent Shorts in this niche (2 searches per run, rotating; 100 API units each)."""
    if not config.YOUTUBE_API_KEY:
        return []
    out = []
    after = (state.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    k = state.now().hour // 6 * 2 + state.now().timetuple().tm_yday
    for q in (NICHE_QUERIES[k % len(NICHE_QUERIES)], NICHE_QUERIES[(k + 1) % len(NICHE_QUERIES)]):
        try:
            r = requests.get("https://www.googleapis.com/youtube/v3/search", timeout=30, params={
                "part": "snippet", "q": q + " #shorts", "type": "video", "videoDuration": "short",
                "order": "viewCount", "publishedAfter": after, "regionCode": config.REGION,
                "relevanceLanguage": config.LANGUAGE, "maxResults": 25, "key": config.YOUTUBE_API_KEY}).json()
            for v in r.get("items", []):
                out.append({"source": f"Niche Shorts ({q})", "title": v["snippet"]["title"],
                            "signal": "top viewed this week", "context": v["snippet"].get("description", "")[:100]})
        except Exception as e:  # noqa: BLE001
            print("niche search failed:", e)
    return out


def collect():
    raw = niche_shorts() + google_trends()  # general YouTube trending isn't useful for this niche; saves API quota
    safe = [t for t in raw if not BLOCKLIST.search(f'{t["title"]} {t["context"]}')]
    print(f"Collected {len(raw)} signals, {len(safe)} passed keyword filter")
    return safe


def pick_topics(signals, history):
    lines = "\n".join(f'- [{s["source"]}] {s["title"]} ({s["signal"]}) {s["context"]}' for s in signals[:120])
    prompt = f"""You are the head writer of "{config.CHANNEL_NAME}", a faceless YouTube Shorts channel of ~30 second
3D-animated curiosity videos (in the spirit of the biggest animated-facts Shorts channels, but 100% original ideas).
Proven winners in this genre: "Why Alcatraz Only Gave Prisoners Hot Showers", "How Ink Tags Stop Clothing Thieves",
"What To Do If Your Car Sinks?", "How Cricket Chirps Predict The Temperature", "The Origin Of The Teddy Bear",
"What Is A Jerboa?", "How The Zombie-Ant Fungus Takes Over An Ant". (Examples of the TYPE only - never copy them.)
Niche: {config.NICHE}. Audience region: {config.REGION}. Language: {config.LANGUAGE}.

Signals (what is getting views right now):
{lines}

Recently covered (do NOT repeat or closely rephrase): {", ".join(history[-60:]) or "none"}

Choose exactly {config.TOPICS_PER_DAY} ideas. Each must be ONE surprising, visual, explainable-in-30-seconds idea
that makes people think "wait, really?". Prefer evergreen curiosity that works worldwide; use the signals only as
inspiration for what people are curious about right now. Use at least 3 different formats:
- "howitworks": how an everyday or hidden thing works ("How Revolving Doors Save Energy")
- "why": the surprising reason behind something ("Why Pilots Dim The Cabin Lights For Landing")
- "whatif": real-science scenario ("What Happens If You Fall Into Quicksand")
- "survival": official-safety-advice "what to do if" ("What To Do If You're Caught In A Rip Current")
- "truestory": well-documented, non-graphic true story or historical oddity
- "creature": a strange real animal or plant and its weird ability
- "hack": a clever, safe, genuinely useful trick

Hard rules - reject any idea that involves politics, religion, gore or graphic injury, real living people, crime
glorification, medical/financial advice, sexual content, brands, or movie/TV/game characters; that needs someone
else's footage; that can't be verified; or that is aimed at young children. Advertiser-friendly, 13+.

Return JSON: {{"topics": [{{"title": "working title in Title Case", "angle": "one sentence: what we SHOW and the payoff",
"format": "howitworks|why|whatif|survival|truestory|creature|hack", "trend_source": "signal that inspired it or evergreen",
"virality_score": 1-10, "why": "why viewers will watch to the end"}}]}}
Sort by virality_score descending."""
    data = llm.ask_json(prompt, temperature=0.8)
    topics = data.get("topics", [])
    # second line of defence
    from .writer import fmt_of
    for t in topics:
        t["format"] = fmt_of(t)
    return [t for t in topics if not BLOCKLIST.search(t["title"] + " " + t["angle"])][: config.TOPICS_PER_DAY]
