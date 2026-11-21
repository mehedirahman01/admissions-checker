from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from admissions.config import settings

# One engine per process. It keeps a pool of open connections to Postgres.
engine = create_engine(settings.database_url)

# Call SessionLocal() to get a session: one unit of work with the database.
SessionLocal = sessionmaker(engine)
