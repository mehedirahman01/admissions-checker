"""Load the NRW university seed list into the database.

Run with: uv run python -m admissions.seed

Safe to run many times (idempotent): existing universities are updated, not duplicated.
"""

import csv
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from admissions.db.models import University
from admissions.db.session import SessionLocal

SEED_FILE = Path(__file__).resolve().parents[2] / "data" / "seeds" / "nrw_universities.csv"


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        # An empty cell in the CSV means "unknown", which is NULL in the database.
        row["programs_page_url"] = row["programs_page_url"] or None
    return rows


def seed_universities(rows: list[dict]) -> None:
    stmt = insert(University).values(rows)
    # Upsert: if a university with this name exists, update it instead of failing.
    stmt = stmt.on_conflict_do_update(
        index_elements=["name"],
        set_={
            "city": stmt.excluded.city,
            "type": stmt.excluded.type,
            "ownership": stmt.excluded.ownership,
            "website": stmt.excluded.website,
            "programs_page_url": stmt.excluded.programs_page_url,
            "updated_at": func.now(),
        },
    )
    with SessionLocal.begin() as session:
        session.execute(stmt)


def main() -> None:
    rows = load_rows(SEED_FILE)
    seed_universities(rows)
    with SessionLocal() as session:
        total = session.scalar(select(func.count()).select_from(University))
    print(f"Seeded {len(rows)} rows from {SEED_FILE.name}. Universities in database: {total}")


if __name__ == "__main__":
    main()
