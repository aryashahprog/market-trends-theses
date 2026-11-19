import io
import re
from contextlib import closing
from urllib.parse import urlsplit

import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from workspace import create_app
from workspace.data import connect


@pytest.fixture()
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "test.sqlite"),
            "SECRET_KEY": "testing-only",
            "DEMO_ENABLED": True,
            "TEAM_EMAILS": {"alex@firm.example", "jess@firm.example"},
            "SMTP_HOST": "smtp.firm.example",
            "SMTP_FROM": "workspace@firm.example",
            "BASE_URL": "https://workspace.firm.example",
        }
    )


def submit(client, path, data=None, csrf_page="/"):
    page = client.get(csrf_page, follow_redirects=True)
    token = re.search(rb'name="csrf" value="([^"]+)"', page.data)
    assert token is not None, page.data
    return client.post(path, data={"csrf": token.group(1).decode(), **(data or {})})


@pytest.fixture()
def demo(app):
    client = app.test_client()
    assert submit(client, "/demo").status_code == 302
    return client


def switch(client, person):
    assert submit(client, "/demo/switch", {"person": person}).status_code == 302


def thesis(client, title, argument, visibility="draft", path="/thesis/new"):
    response = submit(
        client,
        path,
        {
            "title": title,
            "argument": argument,
            "status": "Developing",
            "visibility": visibility,
            "topics": "Research, Testing",
            "reviewed": "2025-09-01",
            "questions": "What changed?",
            "competing": "An opposing view.",
            **({"base_version": edit_token(client, path)} if path.endswith("/edit") else {}),
        },
    )
    assert response.status_code == 302, response.data
    return response.location


def ask(client, question, model=False):
    response = submit(client, "/ask", {"question": question, "use_model": "yes" if model else "no"})
    assert response.status_code == 303, response.data
    return client.get(response.location)


def edit_token(client, path):
    page = client.get(path).data
    match = re.search(rb'name="base_version" value="([0-9a-f]{32})"', page)
    assert match is not None, page
    return match.group(1).decode()


def source(client, target, title, **options):
    return submit(
        client,
        "/research/add",
        {
            "thesis": str(target),
            "source_title": title,
            "source_author": "Source Author",
            "source_visibility": "team",
            "kind": "text",
            "text": "Test content.",
            **options,
        },
    )


def has_citation(client, response, link, exact_passage):
    assert f'href="{link}"'.encode() in response.data
    path, anchor = link.split("#")
    target = client.get(path)
    assert target.status_code == 200
    assert f'id="{anchor}"'.encode() in target.data
    assert exact_passage in target.data


def version_paths(page, thesis_path):
    return [
        match.decode()
        for match in re.findall(thesis_path.encode() + rb'/version/[0-9a-f]{32}(?=")', page)
    ]


def test_default_demo_and_related_views(app, demo):
    homepage = demo.get("/")
    assert b"Fictional demo" in homepage.data
    assert b"Early notes on renewal signals" not in homepage.data
    assert b"Early notes on renewal signals" in demo.get("/my-research").data
    owner_filter = demo.get("/?owner=1&topic=Proprietary+data&status=Developing")
    assert b"durable edge in enterprise AI" in owner_filter.data
    assert b"Workflow automation wins" not in owner_filter.data
    assert b"Workflow automation wins" in demo.get("/thesis/1").data
    assert b"Related theses" in demo.get("/thesis/1").data
    other = app.test_client()
    assert submit(other, "/demo").status_code == 302
    assert other.get("/thesis/1").status_code == 404
    assert other.get("/source/1").status_code == 404


def test_create_edit_share_history_and_comment(demo):
    path = thesis(demo, "Saffron notebook", "Saffronsecret is a private working note.")
    owner_detail = demo.get(path).data
    assert b"Saffronsecret" in owner_detail
    (private_version,) = version_paths(owner_detail, path)
    assert b"Saffronsecret" in ask(demo, "Saffronsecret").data
    assert b"Saffron notebook" not in demo.get("/?q=Saffron").data
    switch(demo, "leo")
    assert demo.get(path).status_code == 404
    assert demo.get(private_version).status_code == 404
    assert b"Saffronsecret" not in ask(demo, "Saffronsecret").data.split(b"ask-results")[-1]

    switch(demo, "maya")
    assert path == thesis(
        demo, "Saffron notebook", "First shareable statement.", "team", path + "/edit"
    )
    assert path == thesis(
        demo, "Saffron notebook", "Second shareable statement.", "team", path + "/edit"
    )
    assert b"Saffronsecret" in demo.get(private_version).data
    assert len(version_paths(demo.get(path).data, path)) == 3
    switch(demo, "leo")
    detail = demo.get(path).data
    assert b"Second shareable statement" in detail
    assert b"First shareable statement" in detail
    assert b"Saffronsecret" not in detail
    assert demo.get(private_version).status_code == 404
    assert demo.get(path + "/version/2").status_code == 404
    latest_version, first_version = version_paths(detail, path)
    assert b"First shareable statement" in demo.get(first_version).data
    assert b"Second shareable statement" in demo.get(latest_version).data
    assert demo.get(path + "/edit").status_code == 403
    assert submit(demo, path + "/edit").status_code == 403
    comment = submit(demo, path + "/discussion", {"comment": "A teammate disagrees."})
    assert comment.status_code == 302
    assert b"A teammate disagrees." in demo.get(path).data


def test_sources_attribution_privacy_and_citation_paths(demo):
    switch(demo, "leo")
    uploaded = source(
        demo,
        1,
        "An external benchmark",
        kind="file",
        file=(io.BytesIO(b"amethystbrowser private test\n\nAnother paragraph."), "notes.txt"),
        source_visibility="draft",
    )
    assert uploaded.status_code == 302, uploaded.data
    path = uploaded.location
    page = demo.get(path).data
    for item in (b"Source Author", b"Leo Park", b"Maya Chen", b"Date added", b"passage-2"):
        assert item in page
    download = demo.get(path + "/download")
    assert b"amethystbrowser" in download.data
    assert download.headers["Content-Disposition"].startswith("attachment;")
    has_citation(demo, ask(demo, "amethystbrowser"), path + "#passage-1", b"amethystbrowser")

    switch(demo, "maya")
    assert demo.get(path).status_code == 404
    assert demo.get(path + "/download").status_code == 404
    assert b"amethystbrowser" not in ask(demo, "amethystbrowser").data.split(b"ask-results")[-1]
    assert b"An external benchmark" not in demo.get("/thesis/1").data
    switch(demo, "leo")
    assert submit(demo, path + "/visibility", {"visibility": "team"}).status_code == 302
    switch(demo, "maya")
    has_citation(demo, ask(demo, "amethystbrowser"), path + "#passage-1", b"amethystbrowser")
    assert submit(demo, path + "/visibility", {"visibility": "draft"}).status_code == 403


def test_add_research_creates_thesis_and_keeps_url_reference_only(demo):
    uploaded = source(
        demo,
        "new",
        "uniquelink",
        kind="link",
        url="https://notes.granola.ai/d/example",
        new_title="New Thesis",
        new_visibility="draft",
        source_visibility="draft",
    )
    assert uploaded.status_code == 302, uploaded.data
    page = demo.get(uploaded.location).data
    assert b"Full text was not imported." in page
    assert b"notes.granola.ai/d/example" in page
    assert b"uniquelink" not in ask(demo, "uniquelink").data.split(b"ask-results")[-1]
    assert b"New Thesis" in demo.get("/my-research").data
    assert source(demo, 1, "bad", kind="link", url="javascript:alert(1)").status_code == 400
    assert source(demo, 4, "bad", source_visibility="team").status_code == 400


def create_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 20 Td (blossom research finding) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out


def test_pdf_and_docx_are_extractable_and_searchable(demo):
    document = Document()
    document.add_paragraph("electrum research finding")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Early result"
    table.rows[0].cells[1].text = "azurite"
    document.add_paragraph("Later qualification")
    docx = io.BytesIO()
    document.save(docx)
    docx.seek(0)
    for name, data, keyword in (
        ("evidence.pdf", create_pdf(), b"blossom"),
        ("evidence.docx", docx, b"electrum"),
    ):
        result = source(demo, 1, name, kind="file", file=(data, name))
        assert result.status_code == 302, result.data
        has_citation(demo, ask(demo, keyword.decode()), result.location + "#passage-1", keyword)
        if name.endswith(".pdf"):
            assert b"Page 1" in demo.get(result.location).data
        else:
            page = demo.get(result.location).data
            assert (
                page.index(b"electrum")
                < page.index(b"Early result")
                < page.index(b"Later qualification")
            )
            assert b"Passage 2" in page and b"Table 1" in page
            has_citation(demo, ask(demo, "azurite"), result.location + "#passage-2", b"azurite")
    assert demo.get("/my-research").data.count(b"Extracted text") >= 2


def test_only_submitter_can_edit_or_delete_sources(demo):
    saved = source(demo, 1, "Phenacite source", text="Phenacite finding.")
    assert saved.status_code == 302
    path = saved.location
    assert b"Edit source" in demo.get(path).data
    revised = submit(demo, path + "/edit", {"title": "Corrected title", "author": "Ada Rao"})
    assert revised.status_code == 303
    page = demo.get(path).data
    assert all(value in page for value in (b"Corrected title", b"Ada Rao", b"Phenacite finding."))
    assert b"Pasted text" in demo.get("/my-research").data

    switch(demo, "leo")
    assert b"Edit source" not in demo.get(path).data
    assert demo.get(path + "/edit").status_code == 403
    assert submit(demo, path + "/edit", {"title": "Not allowed"}).status_code == 403
    assert submit(demo, path + "/delete").status_code == 403
    result = submit(demo, "/ask", {"question": "Phenacite"})
    has_citation(demo, demo.get(result.location), path + "#passage-1", b"Phenacite finding.")

    switch(demo, "maya")
    assert submit(demo, path + "/delete").status_code == 303
    assert demo.get(path).status_code == 404
    assert b"Corrected title" not in demo.get("/thesis/1").data
    assert b"Corrected title" not in demo.get("/my-research").data
    assert b"Phenacite finding." not in ask(demo, "Phenacite").data
    assert source(demo, 1, "Replacement").location != path


def test_duplicate_links_are_checked_without_disclosing_private_sources(demo):
    url = "https://notes.granola.ai/d/intake-test"
    hidden = source(demo, 1, "Hidden URL", kind="link", url=url, source_visibility="draft")
    assert hidden.status_code == 302
    switch(demo, "leo")
    public = source(demo, 1, "Shared URL", kind="link", url=url)
    assert public.status_code == 302
    duplicate = source(demo, 1, "Shared URL again", kind="link", url=url)
    assert duplicate.status_code == 409
    assert public.location.encode() in duplicate.data
    assert hidden.location.encode() not in duplicate.data
    assert b"Reference only" in demo.get("/my-research").data

    other_url = url + "-different"
    loose = source(demo, "", "My unassigned URL", kind="link", url=url, source_visibility="draft")
    assert loose.status_code == 302
    assert submit(demo, loose.location + "/attach", {"thesis": "1"}).status_code == 409
    assert (
        submit(
            demo, public.location + "/edit", {"title": "Shared URL", "url": other_url}
        ).status_code
        == 303
    )
    assert submit(demo, loose.location + "/attach", {"thesis": "1"}).status_code == 302
    assert (
        submit(demo, loose.location + "/edit", {"title": "My URL", "url": other_url}).status_code
        == 409
    )


def test_model_gets_only_authorized_evidence_and_version_links(app, demo, monkeypatch):
    app.config["OPENAI_API_KEY"] = "fake-test-key"
    path = thesis(demo, "Unshared automation", "Hydrangeas appear in this draft automation report.")
    source(
        demo,
        1,
        "Unshared receipt",
        text="Hydrangeas for the automation memo.",
        source_visibility="draft",
    )

    calls = []

    def fake_model(question, evidence):
        calls.append(evidence)
        return [("Separate owner arguments.", [1, 2])]

    monkeypatch.setattr("workspace.ask.model_answer", fake_model)
    switch(demo, "leo")
    comparison = ask(demo, "Where do Maya’s and Leo’s views on enterprise AI overlap?", model=True)
    assert b"AI synthesis" in comparison.data
    assert b"Separate owner arguments" in comparison.data
    assert {doc.owner for doc in calls[-1]} == {"Maya Chen", "Leo Park"}
    assert all(
        "Hydrangeas" not in doc.text and doc.title != "Unshared receipt" for doc in calls[-1]
    )
    (version_path,) = version_paths(demo.get("/thesis/1").data, "/thesis/1")
    has_citation(demo, comparison, version_path + "#argument-1", b"Models will converge")
    assert demo.get(path).status_code == 404
    assert b"There isn" in ask(demo, "which fiduciary redwood microbiome?").data


def test_allowlisted_work_email_magic_link_redeems_once(app, monkeypatch):
    outbox = {}
    monkeypatch.setattr(
        "workspace.auth.deliver", lambda email, token: outbox.update({email: token})
    )
    alex = app.test_client()
    jess = app.test_client()
    stranger = app.test_client()
    assert submit(stranger, "/sign-in", {"email": "stranger@firm.example"}).status_code == 200
    assert not outbox
    for member, client in (("alex", alex), ("jess", jess)):
        email = f"{member}@firm.example"
        sent = submit(client, "/sign-in", {"email": email.upper()})
        assert sent.status_code == 200
        confirm = f"/sign-in/confirm?token={outbox[email]}"
        assert client.get(confirm).status_code == 200
        assert client.get(confirm).status_code == 200  # previewing does not consume it
        assert (
            submit(client, "/sign-in/confirm", {"token": outbox[email]}, confirm).status_code == 302
        )
        assert client.get(confirm).status_code == 400
        assert email.encode() in client.get("/profile").data
    private = thesis(alex, "Specific team draft", "greystonesecret")
    shared = thesis(alex, "Shared among real accounts", "Hello colleagues", "team")
    assert jess.get(private).status_code == 404
    assert b"greystonesecret" not in ask(jess, "greystonesecret").data.split(b"ask-results")[-1]
    assert jess.get(shared).status_code == 200
    assert urlsplit(stranger.get(shared).location).path == "/sign-in"
    assert jess.post("/thesis/new", data={"title": "Untrusted"}).status_code == 400
    assert submit(jess, "/demo/switch", {"person": "maya"}).status_code == 404

    restored = create_app(dict(app.config))
    cookie = alex.get_cookie("session")
    restarted = restored.test_client()
    restarted.set_cookie("session", cookie.value)
    assert b"Specific team draft" in restarted.get(private).data
    assert submit(alex, "/sign-out").status_code == 302
    assert restarted.get(private).status_code == 302

    # Allowlist changes also affect a different, still-active session.
    assert jess.get(shared).status_code == 200
    app.config["TEAM_EMAILS"].remove("jess@firm.example")
    assert jess.get(shared).status_code == 302


def test_compare_does_not_substitute_other_owners_for_missing_people(demo):
    result = ask(demo, "Where do David’s and Hari’s views on enterprise AI overlap?")
    assert b"There isn" in result.data
    assert b"#argument-" not in result.data


def test_quick_note_private_until_explicitly_attached_and_shared(demo):
    saved = submit(demo, "/research/add", {"text": "Sardonyx is an unassigned note."})
    assert saved.status_code == 302
    path = saved.location
    assert b"Not assigned" in demo.get(path).data
    assert (
        b'class="nav-item active" aria-current="location" href="/my-research"'
        in demo.get(path).data
    )
    assert b"Sardonyx is an unassigned note." in demo.get("/my-research").data
    has_citation(demo, ask(demo, "Sardonyx"), path + "#passage-1", b"Sardonyx is")
    assert submit(demo, path + "/visibility", {"visibility": "team"}).status_code == 400
    switch(demo, "leo")
    assert demo.get(path).status_code == 404
    assert submit(demo, path + "/attach", {"thesis": "1", "visibility": "team"}).status_code == 404
    assert b"unassigned note." not in ask(demo, "Sardonyx").data
    switch(demo, "maya")
    attach = submit(demo, path + "/attach", {"thesis": "1", "visibility": "team"})
    assert attach.status_code == 302
    switch(demo, "leo")
    assert b"Thesis owner</dt><dd>Maya Chen" in demo.get(path).data
    assert b"Sardonyx" in demo.get("/thesis/1").data
    has_citation(demo, ask(demo, "Sardonyx"), path + "#passage-1", b"Sardonyx is")


def test_capture_reports_missing_fields_together_and_shares_in_one_submit(demo):
    errors = submit(demo, "/research/add", {"kind": "link", "thesis": "new"})
    assert errors.status_code == 400
    assert b"Enter a source URL. Enter a title for the new thesis." in errors.data
    assert (
        submit(demo, "/research/add", {"text": "Note", "source_visibility": "team"}).status_code
        == 400
    )
    saved = submit(
        demo, "/research/add", {"text": "Citrine note", "thesis": "1", "source_visibility": "team"}
    )
    assert saved.status_code == 302
    switch(demo, "leo")
    assert b"Citrine note" in demo.get(saved.location).data


def test_display_names_are_unique_within_workspace(demo):
    switch(demo, "leo")
    for duplicate in ["Maya Chen", "  mAyA   chen ", "Ｍａｙａ Chen"]:
        response = submit(demo, "/profile", {"name": duplicate})
        assert response.status_code == 400
        assert b"already taken" in response.data
    assert submit(demo, "/profile", {"name": "Leon Park"}).status_code == 302
    assert b"Leon Park" in demo.get("/profile").data
    assert b'<option value="leo" selected>Leon Park</option>' in demo.get("/").data


def test_ask_results_support_get_without_disclosing_private_questions(demo):
    question = "What is the measured human review cost for workflow automation?"
    searched = submit(demo, "/ask", {"question": question})
    assert searched.status_code == 303
    assert "measured" not in searched.location
    first = demo.get(searched.location)
    assert b"No retrieved passage clearly supplies the requested measurement" in first.data
    ref = re.search(rb'href="(/thesis/[^"]+#argument-\d+)"', first.data)
    assert ref is not None
    assert b"Owner" in demo.get(ref.group(1).decode().split("#")[0]).data
    assert first.data == demo.get(searched.location).data
    switch(demo, "leo")
    assert demo.get(searched.location).status_code == 404


def test_saved_answer_is_hidden_when_a_cited_source_is_no_longer_visible(demo):
    saved = source(demo, 1, "Orbitstone benchmark", text="Orbitstone is a shared benchmark.")
    assert saved.status_code == 302
    source_path = saved.location
    switch(demo, "leo")
    saved = submit(demo, "/ask", {"question": "Orbitstone"})
    assert b"Orbitstone is a shared benchmark" in demo.get(saved.location).data
    with closing(connect(demo.application.config["DATABASE"])) as connection, connection:
        connection.execute(
            "UPDATE sources SET visibility = 'draft' WHERE id = ?",
            (int(source_path.rsplit("/", 1)[1]),),
        )
    assert demo.get(source_path).status_code == 404
    result = demo.get(saved.location)
    assert b"no longer accessible" in result.data
    assert b"Orbitstone is a shared benchmark" not in result.data


def test_stale_edit_cannot_overwrite_and_review_date_cannot_be_future(demo):
    path = thesis(demo, "Conflict test", "Initial wording", "team")
    edit = path + "/edit"
    stale = edit_token(demo, edit)
    thesis(demo, "Conflict test", "New argument", "team", edit)
    posts = {
        "title": "Conflict test",
        "argument": "Initial wording",
        "questions": "Unsaved question",
        "status": "Developing",
        "visibility": "team",
        "reviewed": "2096-02-29",
        "base_version": stale,
    }
    conflict = submit(demo, edit, posts)
    assert conflict.status_code == 409
    assert b"Your changes were not saved" in conflict.data and b"Unsaved question" in conflict.data
    assert b"New argument" in demo.get(path).data
    posts["base_version"] = edit_token(demo, edit)
    invalid = submit(demo, edit, posts)
    assert invalid.status_code == 400
    assert b"Last reviewed cannot be in the future" in invalid.data


def test_history_diff_and_restore_respect_draft_visibility(demo):
    path = thesis(demo, "History test", "Private earlier wording")
    edit = path + "/edit"
    (private,) = version_paths(demo.get(path).data, path)
    thesis(demo, "History test", "First shared wording", "team", edit)
    thesis(demo, "History test", "Second shared wording", "team", edit)
    latest, first_shared, _ = version_paths(demo.get(path).data, path)
    token = edit_token(demo, edit)
    switch(demo, "leo")
    prior_shared = demo.get(first_shared)
    assert b"Last reviewed: Sep 01, 2025" in prior_shared.data
    assert b"Private earlier wording" not in prior_shared.data
    assert b"Changes from the previous visible version" not in prior_shared.data
    change = demo.get(latest)
    assert b"Changes from the previous visible version" in change.data
    assert b"First shared wording" in change.data
    assert b"UTC" in change.data
    assert submit(demo, first_shared + "/restore", {"base_version": token}).status_code == 403
    switch(demo, "maya")
    stale_restore = submit(demo, private + "/restore", {"base_version": "stale"})
    assert stale_restore.status_code == 409
    restored = submit(demo, private + "/restore", {"base_version": token})
    assert restored.status_code == 303
    page = demo.get(path).data
    assert len(version_paths(page, path)) == 4 and b"Private earlier wording" in page
    switch(demo, "leo")
    assert demo.get(path).status_code == 404
