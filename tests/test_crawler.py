"""Crawler tests. No real network: httpx.MockTransport plays a fake university website."""

import httpx
from sqlalchemy import select

from admissions.crawler.crawl import crawl_university
from admissions.crawler.fetcher import USER_AGENT, PoliteFetcher
from admissions.crawler.links import extract_links, same_site, score
from admissions.crawler.storage import save_raw
from admissions.db.models import Document, University

ROOT = "https://www.example-uni.de"

PAGES = {
    "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /intern/\n"),
    "/": (
        200,
        "text/html",
        """<a href="/studium/master">Master's programmes</a>
           <a href="/intern/studium">Internal</a>
           <a href="/kantine">Cafeteria menu</a>
           <a href="https://other-site.de/studium">Elsewhere</a>
           <a href="/files/pruefungsordnung.pdf">Exam rules</a>""",
    ),
    "/studium/master": (200, "text/html", '<a href="/studium/master/data-science">DS</a>'),
    "/studium/master/data-science": (200, "text/html", "<p>30 ECTS in mathematics.</p>"),
    "/files/pruefungsordnung.pdf": (200, "application/pdf", "%PDF-1.4 fake"),
}


def fake_site(pages: dict, log: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append(request)
        status, ctype, body = pages.get(request.url.path, (404, "text/html", "not found"))
        return httpx.Response(status, headers={"content-type": ctype}, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler), base_url=ROOT)


def make_fetcher(pages=PAGES, log=None, sleeps=None) -> PoliteFetcher:
    return PoliteFetcher(
        client=fake_site(pages, log),
        sleep=(sleeps.append if sleeps is not None else lambda s: None),
        clock=lambda: 0.0,  # time stands still, so every request must wait
    )


# --- links -------------------------------------------------------------------


def test_extract_links_keeps_relevant_same_site_links():
    links = [link.url for link in extract_links(PAGES["/"][2], ROOT + "/", ROOT)]
    assert ROOT + "/studium/master" in links
    assert ROOT + "/files/pruefungsordnung.pdf" in links
    assert ROOT + "/kantine" not in links  # not about studying
    assert all("other-site.de" not in link for link in links)


def test_admission_pages_score_higher_than_student_life_pages():
    master = score(ROOT + "/studienangebot/master/", "Master")
    rules = score(ROOT + "/zulassung/", "Zulassungsvoraussetzungen")
    unimail = score(ROOT + "/studium/unimail/", "Unimail")
    assert rules > unimail and master > unimail


def test_pages_not_about_studying_are_not_followed():
    assert score(ROOT + "/kantine", "Cafeteria menu") == 0


def test_subdomains_count_as_same_site():
    assert same_site("https://master.example-uni.de/x", ROOT)
    assert not same_site("https://example-uni.de.evil.com/x", ROOT)


# --- fetcher -----------------------------------------------------------------


def test_fetcher_obeys_robots_txt():
    result = make_fetcher().fetch(ROOT + "/intern/studium")
    assert result.error == "blocked by robots.txt"


def test_fetcher_identifies_itself():
    log: list[httpx.Request] = []
    make_fetcher(log=log).fetch(ROOT + "/")
    assert all(r.headers["User-Agent"] == USER_AGENT for r in log)


def test_fetcher_waits_between_requests_to_the_same_host():
    sleeps: list[float] = []
    fetcher = make_fetcher(sleeps=sleeps)
    fetcher.fetch(ROOT + "/")
    fetcher.fetch(ROOT + "/studium/master")
    assert sleeps and all(s >= fetcher.min_delay for s in sleeps)


def test_fetcher_retries_temporary_errors():
    attempts = []

    def flaky(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="ok")

    client = httpx.Client(transport=httpx.MockTransport(flaky))
    fetcher = PoliteFetcher(client=client, sleep=lambda s: None)
    assert fetcher.fetch(ROOT + "/page").ok
    assert len(attempts) == 2


# --- storage -----------------------------------------------------------------


def test_same_content_is_stored_once(tmp_path):
    hash1, path1 = save_raw(b"<p>hello</p>", "text/html", tmp_path)
    hash2, path2 = save_raw(b"<p>hello</p>", "text/html", tmp_path)
    assert hash1 == hash2 and path1 == path2
    assert len(list(tmp_path.rglob("*.html"))) == 1


# --- full crawl --------------------------------------------------------------


def make_uni(session) -> University:
    uni = University(name="Example Uni", city="Dortmund", type="university", website=ROOT)
    session.add(uni)
    session.flush()
    return uni


def test_crawl_follows_relevant_links_and_stores_pages(session, tmp_path):
    uni = make_uni(session)
    run = crawl_university(session, make_fetcher(), uni, raw_dir=tmp_path)

    urls = set(session.scalars(select(Document.url)))
    assert urls == {
        ROOT,
        ROOT + "/studium/master",
        ROOT + "/studium/master/data-science",
        ROOT + "/files/pruefungsordnung.pdf",
    }
    assert run.pages_fetched == 4 and run.pages_failed == 0
    assert len(list(tmp_path.rglob("*.pdf"))) == 1


def test_recrawl_without_changes_changes_nothing(session, tmp_path):
    uni = make_uni(session)
    crawl_university(session, make_fetcher(), uni, raw_dir=tmp_path)
    second = crawl_university(session, make_fetcher(), uni, raw_dir=tmp_path)
    assert second.pages_changed == 0


def test_recrawl_detects_a_changed_page(session, tmp_path):
    uni = make_uni(session)
    crawl_university(session, make_fetcher(), uni, raw_dir=tmp_path)

    changed_site = dict(PAGES)
    changed_site["/studium/master/data-science"] = (200, "text/html", "<p>40 ECTS now.</p>")
    second = crawl_university(session, make_fetcher(changed_site), uni, raw_dir=tmp_path)
    assert second.pages_changed == 1


def test_crawl_stops_at_max_pages(session, tmp_path):
    uni = make_uni(session)
    run = crawl_university(session, make_fetcher(), uni, max_pages=2, raw_dir=tmp_path)
    assert run.pages_fetched == 2


def test_unreachable_site_is_reported_as_a_failure_not_skipped(session, tmp_path):
    def down(request):
        raise httpx.ConnectError("connection refused")

    fetcher = PoliteFetcher(
        client=httpx.Client(transport=httpx.MockTransport(down)), sleep=lambda s: None
    )
    run = crawl_university(session, fetcher, make_uni(session), raw_dir=tmp_path)
    assert run.pages_fetched == 1 and run.pages_failed == 1
    doc = session.scalar(select(Document))
    assert "robots.txt unreachable" in doc.error


def test_crawler_visits_promising_pages_first(session, tmp_path):
    site = {
        "/robots.txt": (404, "text/plain", ""),
        "/": (
            200,
            "text/html",
            """<a href="/studium/unimail">Unimail</a>
               <a href="/studium/tu-app">TU App</a>
               <a href="/studium/master/zulassung">Master admission</a>""",
        ),
        "/studium/master/zulassung": (200, "text/html", "<p>rules</p>"),
    }
    uni = make_uni(session)
    crawl_university(session, make_fetcher(site), uni, max_pages=2, raw_dir=tmp_path)
    urls = set(session.scalars(select(Document.url)))
    assert ROOT + "/studium/master/zulassung" in urls  # chosen before unimail and the app


def test_same_page_under_two_addresses_is_expanded_once(session, tmp_path):
    hub = '<a href="/studium/master/zulassung-ds">DS admission</a>'
    site = {
        "/robots.txt": (404, "text/plain", ""),
        "/": (
            200,
            "text/html",
            '<a href="/studium/master/">Master</a>'
            '<a href="/en/studies/master/">Master (alias)</a>',
        ),
        "/studium/master/": (200, "text/html", hub),
        "/en/studies/master/": (200, "text/html", hub),  # identical content
        "/studium/master/zulassung-ds": (200, "text/html", "<p>rules</p>"),
    }
    log: list[httpx.Request] = []
    crawl_university(session, make_fetcher(site, log), make_uni(session), raw_dir=tmp_path)
    paths = [r.url.path for r in log]
    assert paths.count("/studium/master/zulassung-ds") == 1


def test_double_escaped_ampersands_are_fixed():
    html = '<a href="/studium/liste/?page=2&amp;amp;lang=en">Master list</a>'
    [link] = extract_links(html, ROOT + "/", ROOT)
    assert link.url == ROOT + "/studium/liste/?page=2&lang=en"
