from __future__ import annotations

import json
import random
from pathlib import Path
from urllib.parse import quote_plus, urlparse

TARGET_COUNT = 10_000
OUTPUT_PATH = Path(__file__).resolve().parent / "data" / "demo_posts_10000.json"
TOXIC_RATIO = 0.06
SEARCH_ENGINE_LINK_PATTERNS = [
    "https://www.google.com/search?q={query}",
    "https://www.bing.com/search?q={query}",
    "https://search.yahoo.com/search?p={query}",
    "https://duckduckgo.com/?q={query}",
    "https://www.ecosia.org/search?q={query}",
]


def build_entry(rng: random.Random, index: int) -> dict:
    cities = ["Seattle", "Austin", "Toronto", "Berlin", "Nairobi", "Sao Paulo", "Dublin", "Mumbai", "Melbourne", "Chicago"]
    interests = ["tech", "design", "music", "travel", "science", "gaming", "finance", "health", "books", "movies", "sports", "photography", "fitness", "education", "ai", "startups"]
    topics = [
        "on-call rotation",
        "release process",
        "incident review",
        "new onboarding flow",
        "experiment dashboard",
        "abuse report queue",
        "content ranking",
        "mobile checkout",
        "creator payout timing",
        "session reliability",
    ]
    time_markers = ["this morning", "late last night", "after lunch", "during the weekend rollout", "in today's standup", "after the postmortem"]
    personal_openers = [
        "Small win",
        "Honest update",
        "Need advice",
        "Sharing notes",
        "Hard lesson",
        "Question for folks shipping in production",
        "Team update",
        "Reminder from this week's outage",
    ]
    status_verbs = [
        "shipped",
        "rolled back",
        "patched",
        "documented",
        "retested",
        "deployed",
        "paused",
        "reworked",
        "simplified",
        "tightened",
    ]
    outcomes = [
        "false positives dropped",
        "response times improved",
        "fewer duplicate tickets",
        "handoffs got clearer",
        "fewer escalations overnight",
        "less confusion for new teammates",
        "higher completion rates",
        "cleaner dashboards",
    ]
    concerns = [
        "still seeing edge-case failures",
        "still too much manual triage",
        "still uneven behavior across regions",
        "still noisy alerts around retries",
        "still unclear ownership between teams",
    ]
    practical_replies = [
        "This is useful context. We saw similar behavior and fixed it with smaller rollout waves.",
        "Agree with the direction. A per-region fallback helped us avoid another incident.",
        "Thanks for sharing this. The runbook detail is the part most teams skip.",
        "Helpful thread. If you can share your rollback checklist, that would help a lot.",
        "Strong write-up. We had the same pain point and solved it with ownership on-call maps.",
    ]
    debate_replies = [
        "I disagree with this conclusion, but the evidence is useful and worth discussing.",
        "Respectfully pushing back: this looks like a measurement issue more than a product issue.",
        "I see the trade-off differently; this approach may be too expensive at scale.",
        "I would not ship this as-is, but I appreciate the transparent postmortem.",
        "I think this underestimates failure risk in peak traffic windows.",
    ]
    toxic_replies = [
        "This is stupid. You clearly have no idea what you're doing.",
        "Only an idiot would ship something this broken.",
        "What a garbage take. Stop pretending you can run production.",
        "You're incompetent and your process is a joke.",
        "This is pathetic work from a clueless team.",
    ]
    toxic_posts = [
        "Anyone defending this change is an idiot. The team behind it is useless.",
        "This release is garbage and the owners are incompetent clowns.",
        "Shut up with the fake metrics. This whole effort is pathetic.",
        "The people running this project are frauds and have no clue.",
        "Terrible execution from a clueless group that keeps breaking everything.",
    ]

    city = rng.choice(cities)
    interest_a = rng.choice(interests)
    interest_b = rng.choice([item for item in interests if item != interest_a])
    topic = rng.choice(topics)
    opener = rng.choice(personal_openers)
    when = rng.choice(time_markers)
    verb = rng.choice(status_verbs)
    outcome = rng.choice(outcomes)
    concern = rng.choice(concerns)
    impact = rng.randint(3, 47)
    sample = rng.randint(12, 1800)
    post_type = rng.randint(0, 6)
    is_toxic = rng.random() < TOXIC_RATIO

    if is_toxic:
        content = f"{rng.choice(toxic_posts)} ({city}, {topic}, ref {index + 1})"
        reply_positive = "This tone is not okay. Please critique the system without attacking people."
        reply_negative = rng.choice(toxic_replies)
        quote_commentary = "Quoting this as an example of unproductive hostile discussion we should not normalize."
    elif post_type == 0:
        content = (
            f"{opener}: {when} we {verb} part of our {topic} for {interest_a}. "
            f"Across {sample} sessions, {outcome} by {impact}%. {concern}, but this moved us in the right direction."
        )
        reply_positive = rng.choice(practical_replies)
        reply_negative = rng.choice(debate_replies)
        quote_commentary = "Worth sharing for the data and concrete rollout notes."
    elif post_type == 1:
        content = (
            f"{city} check-in: if your team handles {topic}, what is your best guardrail before a big deploy? "
            f"We had progress on {interest_a}, but last week exposed gaps around {interest_b} handoffs."
        )
        reply_positive = "Great question. Pre-ship game-days reduced our surprises more than any dashboard tweak."
        reply_negative = rng.choice(debate_replies)
        quote_commentary = "Good thread prompt: practical question with real failure context."
    elif post_type == 2:
        content = (
            f"Postmortem summary ({city}): incident lasted {rng.randint(9, 94)} minutes, root cause was a config mismatch, "
            f"and recovery lag came from unclear ownership. We now require rollback rehearsal for {topic} before launch."
        )
        reply_positive = "This is exactly how postmortems should read: clear timeline, root cause, and concrete next steps."
        reply_negative = rng.choice(debate_replies)
        quote_commentary = "Sharing because this is the kind of transparent incident write-up we need more of."
    elif post_type == 3:
        content = (
            f"Hot take on {interest_a}: most teams over-invest in new tooling and under-invest in boring operational docs. "
            f"Our latest results improved only after we cleaned up ownership and runbook quality."
        )
        reply_positive = "Fully agree. Better docs and clearer ownership usually beat another shiny tool."
        reply_negative = rng.choice(debate_replies)
        quote_commentary = "This is a solid debate prompt about operations vs tooling priorities."
    elif post_type == 4:
        content = (
            f"Thread note {index + 1}: two things can be true about {topic} - velocity matters, and safety gates matter. "
            f"We reduced friction and still added stronger checks for high-risk paths."
        )
        reply_positive = "Balanced take. Fast iteration and safety discipline do not have to conflict."
        reply_negative = rng.choice(debate_replies)
        quote_commentary = "Useful nuance here: speed and reliability are both design choices."
    elif post_type == 5:
        content = (
            f"Quick benchmark from our {city} team: median workflow time dropped from {rng.randint(30, 120)}m "
            f"to {rng.randint(12, 65)}m after we simplified {topic}. Still validating results in a second region."
        )
        reply_positive = "Nice improvement. Cross-region validation is the right move before claiming final wins."
        reply_negative = rng.choice(debate_replies)
        quote_commentary = "Sharing for teams asking how to report metrics without overselling results."
    else:
        content = (
            f"I changed my mind on {interest_a}. We blamed users for mistakes that were really product affordance issues. "
            f"After rewriting prompts and defaults, support tickets finally started trending down."
        )
        reply_positive = "Respect for publishing a reversal with evidence. That is rare and useful."
        reply_negative = rng.choice(debate_replies)
        quote_commentary = "Great example of evidence-based course correction."

    link_url = ""
    link_preview: dict = {}
    if rng.random() < 0.27:
        search_phrase = f"{interest_a} {topic} {city} {index + 1}"
        query = quote_plus(search_phrase)
        pattern = rng.choice(SEARCH_ENGINE_LINK_PATTERNS)
        link_url = pattern.format(query=query)
        link_host = urlparse(link_url).netloc.lower()
        link_preview = {
            "title": f"{city} team notes on {topic}",
            "description": "Detailed log with timeline, trade-offs, and follow-up actions.",
            "host": link_host,
            "url": link_url,
        }

    return {
        "content": content,
        "interest_tags": [interest_a, interest_b],
        "link_url": link_url,
        "link_preview": link_preview,
        "reply_positive": reply_positive,
        "reply_negative": reply_negative,
        "quote_commentary": quote_commentary,
    }


def main() -> None:
    rng = random.Random(20260427)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    seen: set[str] = set()
    index = 0
    while len(entries) < TARGET_COUNT:
        entry = build_entry(rng, index)
        fingerprint = entry["content"]
        if fingerprint not in seen:
            entries.append(entry)
            seen.add(fingerprint)
        index += 1

    with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(entries, handle, ensure_ascii=True, indent=2)

    toxic_markers = ("idiot", "stupid", "incompetent", "garbage", "pathetic", "clueless", "shut up", "useless")
    toxic_count = sum(
        1
        for entry in entries
        if any(marker in entry["content"].lower() for marker in toxic_markers)
    )
    print(f"Wrote {len(entries)} entries to {OUTPUT_PATH} (toxic-like entries: {toxic_count})")


if __name__ == "__main__":
    main()
