from __future__ import annotations

from typing import Any

LABEL = {"primary": "Primary source", "corroborated": "Independent corroboration", "reported": "Reported claim"}


def edition_markdown(snap: dict[str, Any]) -> str:
    out = [f"# Signal Atlas — Edition {snap['edition_date']}", "",
           f"_Generated {snap['generated_at']} UTC. Ranking points order the feed; they are not probabilities "
           "or recommendations._", "", f"## {snap['note']['headline']}", "", snap["note"]["summary"], ""]
    for s in snap["signals"]:
        out += [f"## {s['rank']}. {s['title']}", "",
                f"**Sector:** {s['sector']} · **Direction:** {s['direction']} · **Confidence:** {s['confidence']} "
                f"· **Corroboration:** {s['corroboration']}", "",
                f"> {s['thesis_sentence']}", "",
                f"**What changed.** {s['what_changed']}", "",
                f"**Why now (analyst inference).** {s['why_now']}", "",
                f"**Market indication (analyst inference).** {s['market_indication']}", "",
                f"**Startup opportunity.** {s['startup_opportunity']}", "",
                f"**Corporate buyer / use case.** {s['corporate_buyer']}", "",
                f"**Confidence rationale.** {s['confidence_rationale']}", "",
                f"**Next validation.** {s['next_validation']}", "",
                f"**Falsifier.** {s['falsifier']}", "", "**Evidence**", ""]
        for e in s["evidence"]:
            out.append(f"- [{LABEL.get(e['claim_type'], e['claim_type'])} · {e['stance']}] {e['statement']} — "
                       f"[{e['source_name'] or 'source'}]({e['url']}) (published {e['published_at'] or 'n/a'}, "
                       f"retrieved {e['retrieved_at']})")
        out.append("")
    return "\n".join(out)
