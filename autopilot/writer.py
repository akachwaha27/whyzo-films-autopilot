"""Scripts + metadata for Whyzo Films: ~30 second 3D-animated curiosity Shorts.

Formats: howitworks, why, whatif, survival, truestory, creature, hack.
Every video is one short visual story told in 6-8 animated shots with calm, clear narration.
Each scene carries an image_prompt (the 3D shot) and a motion prompt (how that shot moves when animated).
"""
from . import config, llm

# YouTube category ids: 1 Film & Animation, 22 People & Blogs, 24 Entertainment, 26 Howto & Style, 27 Education, 28 Science & Technology
FORMATS = {
    "howitworks": {"emoji": "⚙️", "name": "How it works", "category": "27", "tag": "#howitworks",
                   "playlist": "How Things Work (Animated)"},
    "why": {"emoji": "🤔", "name": "Why…?", "category": "27", "tag": "#didyouknow", "playlist": "Why Does That Happen?"},
    "whatif": {"emoji": "🤯", "name": "What happens if", "category": "27", "tag": "#whatif",
               "playlist": "What Happens If…"},
    "survival": {"emoji": "🛟", "name": "What to do if", "category": "26", "tag": "#survivaltips",
                 "playlist": "What To Do If… (Survival Tips)"},
    "truestory": {"emoji": "📜", "name": "True story", "category": "24", "tag": "#truestory",
                  "playlist": "Unbelievable True Stories"},
    "creature": {"emoji": "🦎", "name": "Strange creature", "category": "27", "tag": "#animals",
                 "playlist": "Weird Animals Explained"},
    "hack": {"emoji": "🛠️", "name": "Clever hack", "category": "26", "tag": "#lifehacks", "playlist": "Clever Hacks"},
}
TITLE_EMOJIS = "😮 🤔 🤨 😱 🤯 😨 😬 😏 😇 🥲"


def fmt_of(topic):
    f = str(topic.get("format", "why")).lower().replace(" ", "").replace("_", "").replace("-", "")
    if f in FORMATS:
        return f
    aliases = {"how": "howitworks", "explainer": "why", "what": "whatif", "story": "truestory", "true": "truestory",
               "animal": "creature", "tips": "hack", "tip": "hack", "survive": "survival"}
    return next((v for k, v in aliases.items() if f.startswith(k)), "why")


RETENTION_RULES = f"""WHYZO FILMS STYLE (a faceless channel of 3D-animated curiosity Shorts - follow strictly):
- One clear visual story, told in {{scene_range}} animated shots. Every sentence must be something we can SEE.
- Sentence 1 is the hook (max 12 words) and states the situation or question directly, e.g.
  "This is why astronauts trim their nails before a spacewalk." / "If your car ever sinks, do this."
  Never greet, never say "in this video", never name the channel.
- Then show the explanation step by step, plainly and calmly, like a friendly narrator walking us through it.
- End on a satisfying payoff or twist in the final shot. The final line may loop back into the first.
- Calm, simple, conversational sentences of 6-14 words. No filler, no hype words.
- Total about {int(config.TARGET_SECONDS * 2.5)} spoken words (~{config.TARGET_SECONDS} seconds).
- "hook_text": 2-5 words shown on screen during the first shot.

CONTENT POLICY (YouTube monetization-safe, advertiser-friendly, general audience 13+):
- No politics, religion, sexual content, drugs, gambling, profanity, gore or graphic injuries.
- Mild peril is fine (a car sinking, being lost, an old prison escape) but show NO blood, wounds, bodies or death,
  and never describe violence in detail. Keep it reassuring and educational.
- Survival content must match standard official safety advice (e.g. Red Cross, national safety agencies). No medical,
  legal or financial advice beyond widely published basic safety steps.
- No claims about real living people. Historical figures and well-documented historical events are fine.
- No movie, TV, game or cartoon characters, brands or logos. Facts must be accurate and widely verifiable.
- Not aimed at young children.

FOR EVERY SCENE ALSO GIVE:
- "image_prompt": the 3D shot for that moment: subject, action, setting, camera angle (close-up / wide / top-down /
  cross-section / inside-the-object view). Describe generic people as "a man in a blue hoodie", "a woman in a yellow
  raincoat" and keep the SAME description for the same character in every scene. No text, signs, logos or real people.
- "motion": 5-12 words describing how the shot moves when animated (e.g. "water slowly rises over the car window",
  "camera pushes in as the gear starts turning").
- "stock_queries": 2 short generic stock searches for that moment (backup only).

METADATA:
- "title": Title Case, max 55 characters, ending with exactly ONE emoji from: {TITLE_EMOJIS}
  Use proven patterns: "How … Works", "Why … ", "What Happens If …", "What To Do If …", "The … That …", "He/She … ".
  Honest: the video must deliver what the title promises.
- "primary_keyword": the 2-4 word phrase people would search (lowercase).
- "description": line 1 = one-sentence summary containing the primary_keyword (max 150 chars);
  line 2 = one more sentence with a related search phrase.
- "thumbnail_text": 2-4 punchy words (different from the title).
- "hashtags": exactly 4: "#shorts", one broad topic hashtag, one niche hashtag, and "{{format_tag}}".
- "tags": 10-15 lowercase search phrases about this exact video (no #, no brand or people names).
- "pinned_comment": a friendly first comment (max 200 chars): a bonus fact or a question viewers want to answer.
- "key_facts": every factual claim made."""

STRUCTURES = {
    "howitworks": """FORMAT: "How X works". Show the object, then reveal what happens inside (cross-section / x-ray /
inside view shots work great), step by step, ending with the clever bit that makes it work.""",
    "why": """FORMAT: "Why X". Start with the surprising thing, show the problem it solves or the reason behind it, then the
payoff explanation. Example: "Why some astronauts remove their fingernails".""",
    "whatif": """FORMAT: "What happens if X". Show the scenario and the step-by-step consequences, grounded in real
science. Keep it calm and educational, never graphic.""",
    "survival": """FORMAT: "What to do if X". Show the danger, then 3-4 clear actions in order, as recommended by official
safety agencies, ending with the person safe. Never risky or unofficial advice.""",
    "truestory": """FORMAT: short TRUE story or historical event, well documented in reliable sources (no living private
people, no crime glorification, nothing graphic). Clear beginning, a turning point, and a surprising or uplifting ending.
The description MUST start its second line with "Based on a true story." """,
    "creature": """FORMAT: strange real animal or plant. Show what it looks like, its weird ability or habit, and the
surprising reason it evolved that way. Not gross for its own sake.""",
    "hack": """FORMAT: clever, genuinely useful and safe hack or trick (home, kitchen, travel, tech, outdoors). Show the
problem, the trick step by step, and the satisfying result. Nothing dangerous.""",
}


def write_package(topic):
    fmt = fmt_of(topic)
    info = FORMATS[fmt]
    feedback = topic.get("feedback")
    prompt = f"""Write an ORIGINAL vertical YouTube Short package.
Topic: {topic['title']}
Angle: {topic.get('angle', '')}
Language: {config.LANGUAGE}. Channel: {config.CHANNEL_NAME} (AI-animated facts & stories).
{f'CHANNEL OWNER FEEDBACK ON THE PREVIOUS VERSION - apply it: {feedback}' if feedback else ''}

{STRUCTURES[fmt]}

{RETENTION_RULES.replace('{format_tag}', info['tag']).replace('{scene_range}', '6-8')}

Return JSON:
{{"primary_keyword": "...", "title": "...", "hook_text": "...", "thumbnail_text": "...", "description": "...", "hashtags": ["#shorts", "...", "...", "{info['tag']}"],
  "tags": ["..."], "pinned_comment": "...", "scenes": [{{"text": "narration", "badge": "", "label": "",
  "image_prompt": "...", "motion": "...", "stock_queries": ["...", "..."]}}], "key_facts": ["..."]}}"""
    pkg = llm.ask_json(prompt, temperature=0.75)
    pkg["format"] = fmt
    pkg["category"] = info["category"]
    _normalize(pkg, fmt)
    pkg["script"] = " ".join(s["text"].strip() for s in pkg["scenes"])
    return pkg


def _normalize(pkg, fmt):
    scenes = [s for s in pkg.get("scenes", []) if str(s.get("text", "")).strip()]
    for s in scenes:
        q = s.get("stock_queries") or [s.get("stock_query", "")]
        s["stock_queries"] = [x for x in q if x][:3] or [pkg.get("title", "abstract background")]
        s["stock_query"] = s["stock_queries"][0]
        s["badge"] = str(s.get("badge") or "").strip()[:8]
        s["label"] = str(s.get("label") or "").strip()[:60]
        s["image_prompt"] = str(s.get("image_prompt") or s["stock_query"]).strip()[:600]
        s["motion"] = str(s.get("motion") or "slow cinematic camera push-in").strip()[:200]
    pkg["scenes"] = scenes
    tags = [t if t.startswith("#") else "#" + t for t in pkg.get("hashtags", []) if t]
    tags = [t.replace(" ", "") for t in tags]
    if "#shorts" not in [t.lower() for t in tags]:
        tags.insert(0, "#shorts")
    if FORMATS[fmt]["tag"] not in tags:
        tags.append(FORMATS[fmt]["tag"])
    pkg["hashtags"] = list(dict.fromkeys(tags))[:5]
    pkg["tags"] = [str(t).lstrip("#").strip() for t in pkg.get("tags", []) if t][:15]
    pkg["hook_text"] = str(pkg.get("hook_text") or "").strip()[:40]
    pkg["primary_keyword"] = str(pkg.get("primary_keyword") or "").lower().strip()[:60]
    pkg["pinned_comment"] = str(pkg.get("pinned_comment") or "").strip()[:500]
    pkg["thumbnail_text"] = str(pkg.get("thumbnail_text") or pkg["hook_text"]).strip()[:40]
    pkg["title"] = str(pkg.get("title", "")).strip()[:95]
    if fmt == "truestory" and "true story" not in pkg.get("description", "").lower():
        pkg["description"] = pkg.get("description", "").rstrip() + "\nBased on a true story."


def review(pkg):
    """Independent pass: is this safe, advertiser-friendly, policy compliant and factually grounded?"""
    evidence = ""
    if config.FACT_CHECK:
        try:
            from . import factcheck
            found = factcheck.gather(pkg)
            pkg["fact_sources"] = found["sources"]
            evidence = found["evidence"]
        except Exception as e:  # noqa: BLE001
            print("fact-check skipped:", str(e)[:150])
    evidence_rules = f"""

WIKIPEDIA EVIDENCE (article intros fetched for the claims above):
{evidence}

Fact-check rules: compare every FACT and every number/rank in the SCRIPT with this evidence.
Reject (approved=false) and name the claim in "issues" if the evidence contradicts it (wrong number,
wrong order, wrong name). A claim the evidence doesn't mention is fine only if it is common knowledge;
reject surprising specific numbers that nothing supports. Small rounding ("about 11 km") is fine.""" if evidence else ""
    prompt = f"""You are a strict YouTube content-policy, advertiser-friendliness and fact-check reviewer.
Review this Short and return JSON {{"approved": true/false, "issues": ["..."],
"fixed_title": "", "fixed_script_needed": true/false}}.

Reject (approved=false) if ANY of: political, religious or divisive content; graphic violence, gore, injuries,
blood or death described in detail; glorifying crime; medical/legal/financial advice (basic official safety steps
are fine); survival advice that contradicts official safety guidance; statements about real living people;
movie/TV/game characters or brands; misleading title the video doesn't deliver; likely false facts; fiction
presented as true; sexual content; mocking any group; content unsuitable for a general 13+ audience.
Mild peril, well-documented history and educational "what happens if" science are FINE.
Minor title issues only: approve and provide fixed_title (max 60 chars).

FORMAT: {pkg.get('format')}
TITLE: {pkg['title']}
DESCRIPTION: {pkg['description']}
SCRIPT: {pkg['script']}
FACTS: {pkg.get('key_facts')}{evidence_rules}"""
    verdict = llm.ask_json(prompt, temperature=0.0)
    if verdict.get("fixed_title"):
        pkg["title"] = str(verdict["fixed_title"])[:95]
    return bool(verdict.get("approved")) and not verdict.get("fixed_script_needed"), verdict.get("issues", [])


def build_description(pkg, credits, human_reviewed=False):
    tags = " ".join(pkg["hashtags"][:5])
    review_line = ("Original script written with AI assistance, fact-checked and safety-reviewed"
                   + (", and approved by the channel owner." if human_reviewed else "."))
    lines = [pkg["description"].strip(), "", f"🔔 Subscribe for a new \"wait, really?\" every day: {config.CHANNEL_HANDLE}",
             "", tags, "", f"{config.CHANNEL_NAME} - AI-animated facts & stories.",
             "", "— Credits & disclosure —", review_line,
             "Visuals are AI-generated 3D animation; narration is an AI voice."]
    lines += credits
    lines.append("No other creators' videos were reused.")
    return "\n".join(lines)
