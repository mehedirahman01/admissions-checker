from sqlalchemy import func, select

from admissions.db.models import University
from admissions.seed import SEED_FILE, load_rows, seed_universities


def test_seed_file_has_no_duplicate_names():
    names = [row["name"] for row in load_rows(SEED_FILE)]
    assert len(names) == len(set(names))


def test_seeding_twice_gives_the_same_result(session):
    rows = load_rows(SEED_FILE)

    seed_universities(session, rows)
    seed_universities(session, rows)  # idempotent: no duplicates, no error

    count = session.scalar(select(func.count()).select_from(University))
    assert count == len(rows)
