"""Crawl one university, best-first: the most promising link is always visited next
(a priority queue), so program and admission pages are reached before student-life pages.

Safe to stop and re-run at any time: every page is saved as soon as it is fetched,
and a page whose content did not change is not counted as changed."""

import heapq
import itertools
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from admissions.crawler.fetcher import PoliteFetcher
from admissions.crawler.links import canonical_url, extract_links
from admissions.crawler.storage import RAW_DIR, content_hash, save_raw
from admissions.db.models import CrawlRun, Document, University


def record(session: Session, university: University, run: CrawlRun, result, raw_dir: Path) -> bool:
    """Save one fetch result. Returns True if the content is new or changed."""
    now = datetime.now(UTC)
    doc = session.scalar(select(Document).where(Document.url == result.url))
    if doc is None:
        doc = Document(university_id=university.id, url=result.url)
        session.add(doc)

    doc.status_code = result.status_code
    doc.content_type = result.content_type
    doc.last_fetched_at = now
    doc.crawl_run_id = run.id
    doc.error = result.error

    changed = False
    if result.ok:
        digest, path = save_raw(result.body, result.content_type, raw_dir)
        if doc.content_hash != digest:
            changed = doc.content_hash is not None  # first sighting is "new", not "changed"
            doc.content_hash = digest
            doc.storage_path = str(path.relative_to(raw_dir))
            doc.last_changed_at = now
    return changed


def crawl_university(
    session: Session,
    fetcher: PoliteFetcher,
    university: University,
    max_pages: int = 100,
    max_depth: int = 2,
    raw_dir: Path = RAW_DIR,
) -> CrawlRun:
    run = CrawlRun()
    session.add(run)
    session.commit()

    start_urls = [u for u in (university.programs_page_url, university.website) if u]
    order = itertools.count()  # tie-breaker: equal scores keep discovery order
    # heapq pops the smallest item first, so scores are stored negative.
    queue = [(-100, next(order), url, 0) for url in start_urls]
    seen = set(start_urls)
    seen_hashes: set[str] = set()  # content already expanded in this run

    while queue and run.pages_fetched < max_pages:
        _neg_score, _, url, depth = heapq.heappop(queue)
        result = fetcher.fetch(url)
        if result.blocked:
            continue  # robots.txt forbids it: not fetched, not stored
        run.pages_fetched += 1
        if not result.ok:
            run.pages_failed += 1
        if record(session, university, run, result, raw_dir):
            run.pages_changed += 1
        session.commit()  # progress is kept even if the next page crashes

        is_html = result.ok and result.content_type == "text/html"
        if not is_html or depth >= max_depth:
            continue

        # Many sites serve the same page under several addresses. Expand each page once:
        # skip it if we already expanded the same content, or its canonical address.
        page_url = result.final_url or url
        digest = content_hash(result.body)
        canonical = canonical_url(result.body, page_url)
        if digest in seen_hashes or (canonical and canonical != page_url and canonical in seen):
            continue
        seen_hashes.add(digest)
        if canonical:
            seen.add(canonical)
        for link in extract_links(result.body, page_url, university.website):
            if link.url not in seen:
                seen.add(link.url)
                heapq.heappush(queue, (-link.score, next(order), link.url, depth + 1))

    run.finished_at = datetime.now(UTC)
    session.commit()
    return run
