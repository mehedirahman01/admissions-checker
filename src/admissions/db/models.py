"""Database tables. One class = one table."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Predictable names for constraints, so migrations can find and change them later.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class Timestamps:
    """Adds created_at and updated_at to every table that uses it."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --- Universities and programs -------------------------------------------


class University(Timestamps, Base):
    __tablename__ = "university"
    __table_args__ = (
        CheckConstraint("type IN ('university', 'applied_sciences', 'arts')", name="type"),
        CheckConstraint("ownership IN ('public', 'private', 'church')", name="ownership"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    city: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20))
    ownership: Mapped[str] = mapped_column(String(10), server_default="public")
    website: Mapped[str] = mapped_column(String(500))
    programs_page_url: Mapped[str | None] = mapped_column(String(500))


class Program(Timestamps, Base):
    __tablename__ = "program"
    __table_args__ = (
        # The crawler can never create the same program twice.
        UniqueConstraint("university_id", "name", "degree", name="uq_program_identity"),
        CheckConstraint("degree IN ('bachelor', 'master')", name="degree"),
        CheckConstraint("language IN ('german', 'english', 'mixed')", name="language"),
        CheckConstraint(
            "application_route IN ('uni_assist', 'direct', 'unknown')", name="route"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(
        ForeignKey("university.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(300))
    degree: Mapped[str] = mapped_column(String(10))
    language: Mapped[str | None] = mapped_column(String(10))
    ects_length: Mapped[int | None]
    application_route: Mapped[str] = mapped_column(String(20), server_default="unknown")
    fee_eur_per_semester: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    url: Mapped[str] = mapped_column(String(500))


# --- Rules, deadlines and their proof ------------------------------------

APPLICANT_GROUP_CHECK = "applicant_group IN ('all', 'eu', 'non_eu')"


class Requirement(Timestamps, Base):
    __tablename__ = "requirement"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('subject_ects', 'total_ects', 'grade', 'language', 'other')",
            name="kind",
        ),
        CheckConstraint(APPLICANT_GROUP_CHECK, name="applicant_group"),
        # A rule has a number ("30 ECTS"), a text ("relevant bachelor's"), or both.
        CheckConstraint(
            "value_num IS NOT NULL OR value_text IS NOT NULL", name="has_value"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(
        ForeignKey("program.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    subject_area: Mapped[str | None] = mapped_column(String(100))
    value_num: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(20))
    applicant_group: Mapped[str] = mapped_column(String(10), server_default="all")


class Deadline(Timestamps, Base):
    __tablename__ = "deadline"
    __table_args__ = (
        CheckConstraint("semester IN ('winter', 'summer')", name="semester"),
        CheckConstraint(APPLICANT_GROUP_CHECK, name="applicant_group"),
        UniqueConstraint(
            "program_id", "semester", "applicant_group", name="uq_deadline_per_group"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(
        ForeignKey("program.id", ondelete="CASCADE"), index=True
    )
    semester: Mapped[str] = mapped_column(String(10))
    applicant_group: Mapped[str] = mapped_column(String(10), server_default="all")
    deadline_date: Mapped[date] = mapped_column(Date)


class Source(Timestamps, Base):
    """The proof for one requirement or one deadline: URL plus quoted sentence."""

    __tablename__ = "source"
    __table_args__ = (
        # Exactly one of the two must be set.
        CheckConstraint(
            "num_nonnulls(requirement_id, deadline_id) = 1", name="exactly_one_target"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    requirement_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE"), index=True
    )
    deadline_id: Mapped[int | None] = mapped_column(
        ForeignKey("deadline.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(500))
    quote: Mapped[str] = mapped_column(Text)
    document_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 in hex
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --- Pipeline monitoring and change tracking -----------------------------


class CrawlRun(Base):
    __tablename__ = "crawl_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pages_fetched: Mapped[int] = mapped_column(server_default="0")
    pages_changed: Mapped[int] = mapped_column(server_default="0")
    pages_failed: Mapped[int] = mapped_column(server_default="0")


class Document(Base):
    """One fetched URL (HTML page or PDF). The raw file lives on disk, named by its hash."""

    __tablename__ = "document"

    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(
        ForeignKey("university.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(2000), unique=True)
    status_code: Mapped[int | None]
    content_type: Mapped[str | None] = mapped_column(String(100))
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    storage_path: Mapped[str | None] = mapped_column(String(300))
    error: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crawl_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_run.id", ondelete="SET NULL")
    )


class ChangeEvent(Base):
    __tablename__ = "change_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(
        ForeignKey("program.id", ondelete="CASCADE"), index=True
    )
    crawl_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_run.id", ondelete="SET NULL")
    )
    field: Mapped[str] = mapped_column(String(100))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# --- Transcript check (rows are deleted after the check) -----------------


class TranscriptCourse(Base):
    __tablename__ = "transcript_course"

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[uuid.UUID] = mapped_column(index=True)
    course_name: Mapped[str] = mapped_column(String(300))
    ects: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    grade: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    subject_area: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# --- Shortlists and deadline reminders -----------------------------------


class Shortlist(Timestamps, Base):
    """Found by a long random token in its link, never by id. No account needed."""

    __tablename__ = "shortlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str | None] = mapped_column(String(320))  # only after opt-in
    email_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ShortlistItem(Base):
    __tablename__ = "shortlist_item"
    __table_args__ = (
        UniqueConstraint("shortlist_id", "program_id", name="uq_shortlist_program"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shortlist_id: Mapped[int] = mapped_column(
        ForeignKey("shortlist.id", ondelete="CASCADE"), index=True
    )
    program_id: Mapped[int] = mapped_column(
        ForeignKey("program.id", ondelete="CASCADE"), index=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Reminder(Base):
    """One planned email. The unique constraint plus sent_at means: sent exactly once."""

    __tablename__ = "reminder"
    __table_args__ = (
        UniqueConstraint(
            "shortlist_item_id", "deadline_id", "send_at", name="uq_reminder_once"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shortlist_item_id: Mapped[int] = mapped_column(
        ForeignKey("shortlist_item.id", ondelete="CASCADE"), index=True
    )
    deadline_id: Mapped[int] = mapped_column(
        ForeignKey("deadline.id", ondelete="CASCADE"), index=True
    )
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
