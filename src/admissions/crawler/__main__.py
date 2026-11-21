"""Run the crawler from the command line.

Examples:
    uv run python -m admissions.crawler --university "TU Dortmund" --max-pages 30
    uv run python -m admissions.crawler --all --max-pages 100
"""

import argparse

from sqlalchemy import select

from admissions.crawler.crawl import crawl_university
from admissions.crawler.fetcher import PoliteFetcher
from admissions.db.models import University
from admissions.db.session import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl NRW university websites.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--university", help="part of the name or website, e.g. 'dortmund'")
    target.add_argument("--all", action="store_true", help="crawl every university")
    parser.add_argument("--max-pages", type=int, default=100, help="per university")
    parser.add_argument("--max-depth", type=int, default=2, help="links away from the start")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    args = parser.parse_args()

    fetcher = PoliteFetcher(min_delay=args.delay)
    with SessionLocal() as session:
        query = select(University).order_by(University.name)
        if args.university:
            pattern = f"%{args.university}%"
            query = query.where(University.name.ilike(pattern) | University.website.ilike(pattern))
        universities = session.scalars(query).all()
        if not universities:
            raise SystemExit(f"No university matches {args.university!r}. Did you run the seed?")

        for uni in universities:
            print(f"Crawling {uni.name} ({uni.website}) ...")
            run = crawl_university(session, fetcher, uni, args.max_pages, args.max_depth)
            print(
                f"  fetched {run.pages_fetched}, changed {run.pages_changed}, "
                f"failed {run.pages_failed}"
            )


if __name__ == "__main__":
    main()
