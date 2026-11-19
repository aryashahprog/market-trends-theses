import json

from .data import db, now, person, save_thesis

PEOPLE = {
    "maya": ("maya@demo.invalid", "Maya Chen"),
    "leo": ("leo@demo.invalid", "Leo Park"),
    "nora": ("nora@demo.invalid", "Nora Ellis"),
}

THESES = (
    (
        "maya",
        "The durable edge in enterprise AI is workflow context",
        "Developing",
        "Enterprise AI, Proprietary data",
        "Models will converge, but enterprise AI vendors with access to proprietary workflow data "
        "can improve on real exceptions and approvals. I would back products that turn repeated "
        "workflow events into a measurable feedback loop, not products with raw records alone.",
        "How frequently must a workflow run before its feedback loop becomes defensible?",
        "If customers can carry their workflow histories across vendors, owning the "
        "workflow interface may be more valuable than exclusive access to the data.",
    ),
    (
        "leo",
        "Workflow automation wins at the exception layer",
        "Active",
        "Enterprise AI, Workflow automation",
        "I think enterprise AI retains customers when it reliably handles exceptions in a workflow. "
        "Proprietary data can help, but it is not required: access to the right action and human "
        "review is a more durable advantage than retaining workflow data.",
        "How much human review can an exception pipeline sustain before economics break down?",
        "A generic automation platform may eventually handle enough exceptions if integrations "
        "and evaluation standards become interchangeable.",
    ),
    (
        "nora",
        "Governance could become the control plane for AI",
        "Exploring",
        "Enterprise AI, Governance",
        "Compliance teams will increasingly want a single place to review model permissions, "
        "trace decisions and handle incident approvals. Distribution through infrastructure teams "
        "might matter more than building a standalone audit interface.",
        "Can buyers justify a separate budget for this layer?",
        "Cloud platforms may bundle just enough audit support to limit standalone demand.",
    ),
    (
        "maya",
        "Early notes on renewal signals",
        "Exploring",
        "Retention",
        "Early thoughts only: renewal behavior may follow who receives the first clear time saving.",
        "Interview operators before sharing this with the team.",
        "",
    ),
)


def seed(space: str) -> int:
    ids = {slug: person(space, *profile) for slug, profile in PEOPLE.items()}
    entry = []
    for index, (owner, title, status, topics, argument, questions, competing) in enumerate(THESES):
        entry.append(
            save_thesis(
                {
                    "title": title,
                    "status": status,
                    "topics": topics,
                    "argument": argument,
                    "questions": questions,
                    "competing": competing,
                    "visibility": "draft" if index == 3 else "team",
                    "reviewed": "",
                },
                space,
                ids[owner],
            )
        )
    for thesis, who, name, source_author, passage in (
        (
            entry[1],
            "nora",
            "Pilot debrief: where automation stopped",
            "Fieldwork Lab (fictional)",
            "In a fictional invoice pilot, automation handled standard approvals but failed to "
            "route undocumented exceptions. Manual review erased much of the time saved, "
            "challenging the assumption that automation cuts costs at low exception volumes.",
        ),
        (
            entry[0],
            "leo",
            "Portability experiment",
            "Elliot Moss (fictional)",
            "In a fictional procurement trial, switching vendors took two weeks once the customer "
            "exported its audit history. The trial challenges the idea that historical proprietary "
            "data alone is enough to prevent switching.",
        ),
    ):
        db().execute(
            """INSERT INTO sources (thesis_id, added_by, added, title, author, visibility,
            kind, url, filename, passage_data) VALUES (?,?,?,?,?,'team','text','','',?)""",
            (
                thesis,
                ids[who],
                now(),
                name,
                source_author,
                json.dumps([{"label": "", "text": passage}]),
            ),
        )
    db().execute(
        "INSERT INTO comments (thesis_id, person_id, body, created) VALUES (?, ?, ?, ?)",
        (
            entry[0],
            ids["leo"],
            "I’d like to compare this across workflows with different "
            "exception rates. Lock-in might depend on more than the data export.",
            now(),
        ),
    )
    return ids["maya"]
