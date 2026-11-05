from __future__ import annotations

from typing import Any

LABEL = {"primary": "Primary source", "corroborated": "Independent corroboration", "reported": "Reported claim"}
ROLE = {"buyer": "Likely buyer", "benefits": "Benefits", "pressure": "Faces pressure"}


def _ev(e: dict[str, Any]) -> str:
    return (f"- [{LABEL.get(e['claim_type'], e['claim_type'])}] {e['statement']} — "
            f"[{e.get('source_name') or 'source'}]({e['url']}) (published {e.get('published_at') or 'n/a'}, "
            f"retrieved {e.get('retrieved_at') or 'n/a'})")


def signal_markdown(s: dict[str, Any]) -> list[str]:
    out = [f"## {s['rank']}. {s['title']}", "",
           f"**Sector:** {s['sector']} · **Direction:** {s['direction']} · **Confidence:** {s['confidence']} "
           f"· **Corroboration:** {s['corroboration']}", ""]
    stamps = [f"evidence reviewed {s['evidence_reviewed_at']}" if s.get("evidence_reviewed_at") else None,
              f"thesis revised {s['updated_at']}" if s.get("updated_at") else None]
    if any(stamps):
        out += ["_" + "; ".join(x for x in stamps if x) + " (UTC)_", ""]
    out += ["### The takeaway", "", s.get("takeaway") or s["dek"], ""]
    if s.get("caveats"):
        out += ["**Keep in mind**", ""] + [f"- {c}" for c in s["caveats"]] + [""]
    out += [f"> {s['thesis_sentence']}", ""]
    ch = s.get("since_last")
    if ch:
        out += [f"### Since the last edition ({ch['previous_edition']})", ""]
        out += [f"- New evidence: {e['statement']}" for e in ch.get("new_evidence") or []]
        out += [f"- {r['what']} revised (was: {r['from']})" for r in ch.get("revised") or []]
        if ch.get("confidence"):
            out.append(f"- Confidence {ch['confidence']['from']} → {ch['confidence']['to']}")
        out += [f"- Validation: {v.get('outcome', v)}" for v in ch.get("validation_outcomes") or []]
        out += [f"- Open question: {q}" for q in ch.get("open_questions") or []]
        out.append("")
    if s.get("audiences"):
        out += ["### Who this matters to (analyst inference)", ""]
        for a in s["audiences"]:
            out += [f"**{a['segment']} — {ROLE.get(a['role'], a['role'])}**", "", f"- Who: {a['who']}",
                    f"- Impact: {a['impact']}", f"- Possible action: {a['action']}",
                    f"- Trigger to watch: {a['trigger']}", ""]
    out += ["### What changed", ""]
    out += [f"- {p}" for p in s["changed_points"]] if s.get("changed_points") else [s["what_changed"]]
    out += ["", f"**Why now (analyst inference).** {s['why_now']}", ""]
    out += ["### Business implications (analyst inference)", ""]
    for i in s.get("implications") or []:
        out.append(f"- {i['trend']} → {i['problem']} → {i['buyer']} → {i['solution']} → investigate: {i['investigate']}")
    if not s.get("implications"):
        out += [f"- Startup opportunity: {s.get('startup_opportunity', '')}",
                f"- Corporate buyer / use case: {s.get('corporate_buyer', '')}"]
    out += ["", f"**Market indication.** {s['market_indication']}", ""]
    if s.get("customer_validation"):
        out += [f"**Customer validation.** {s['customer_validation']}", ""]
    out += [f"**Next validation.** {s['next_validation']}", "", "### What could change our view", ""]
    out += [_ev(e) for e in s["evidence"] if e["stance"] == "challenges"]
    out += ["", f"**Falsifier.** {s['falsifier']}", ""]
    out += [f"- Watch: {t}" for t in s.get("view_triggers") or []]
    out += ["", "### Sources and methodology", "", f"**Confidence rationale.** {s['confidence_rationale']}", ""]
    out += [_ev(e) for e in s["evidence"] if e["stance"] != "challenges"]
    out.append("")
    return out


def edition_markdown(snap: dict[str, Any]) -> str:
    note = snap["note"]
    out = [f"# Market Trends → Theses — Edition {snap['edition_date']}", "",
           f"_Generated {snap['generated_at']} UTC. Ranking points reflect editorial prioritization; they are not "
           "probabilities or recommendations. Who-it-matters-to and business implications are analyst inference._",
           "", f"## {note['headline']}", "", note["summary"], ""]
    if note.get("takeaways"):
        out += [f"{n}. {t}" for n, t in enumerate(note["takeaways"], 1)] + [""]
    for s in snap["signals"]:
        out += signal_markdown(s)
    return "\n".join(out)
