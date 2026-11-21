"""Tests for the rules we designed into the database, not for SQLAlchemy itself."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from admissions.db.models import Deadline, Program, Requirement, Source, University


def make_university(session, name="Test University") -> University:
    uni = University(name=name, city="Dortmund", type="university", website="https://example.org")
    session.add(uni)
    session.flush()  # sends the INSERT now, so uni.id is set
    return uni


def make_program(session, university, name="Data Science", degree="master") -> Program:
    program = Program(
        university_id=university.id, name=name, degree=degree, url="https://example.org/ds"
    )
    session.add(program)
    session.flush()
    return program


def make_source(**target) -> Source:
    return Source(
        url="https://example.org/rules.pdf",
        quote="Applicants need at least 30 ECTS in mathematics.",
        document_hash="0" * 64,
        fetched_at=datetime.now(UTC),
        **target,
    )


def test_duplicate_program_is_rejected(session):
    uni = make_university(session)
    make_program(session, uni)

    with pytest.raises(IntegrityError, match="uq_program_identity"):
        make_program(session, uni)


def test_same_program_name_with_other_degree_is_allowed(session):
    uni = make_university(session)
    make_program(session, uni, degree="master")
    make_program(session, uni, degree="bachelor")  # no error


def test_source_needs_exactly_one_target(session):
    uni = make_university(session)
    program = make_program(session, uni)
    requirement = Requirement(
        program_id=program.id, kind="subject_ects", subject_area="mathematics", value_num=30
    )
    deadline = Deadline(program_id=program.id, semester="winter", deadline_date=date(2027, 7, 15))
    session.add_all([requirement, deadline])
    session.flush()

    session.add(make_source(requirement_id=requirement.id))  # exactly one: fine
    session.flush()

    for bad in ({}, {"requirement_id": requirement.id, "deadline_id": deadline.id}):
        with pytest.raises(IntegrityError, match="ck_source_exactly_one_target"):
            with session.begin_nested():  # savepoint, so the failure doesn't end the test
                session.add(make_source(**bad))
                session.flush()


def test_requirement_needs_a_value(session):
    uni = make_university(session)
    program = make_program(session, uni)

    with pytest.raises(IntegrityError, match="ck_requirement_has_value"):
        session.add(Requirement(program_id=program.id, kind="other"))
        session.flush()


def test_deleting_a_university_deletes_its_programs_and_rules(session):
    uni = make_university(session)
    program = make_program(session, uni)
    session.add(Requirement(program_id=program.id, kind="grade", value_num=2.5))
    session.flush()

    session.delete(uni)
    session.flush()

    assert session.scalar(select(func.count()).select_from(Program)) == 0
    assert session.scalar(select(func.count()).select_from(Requirement)) == 0


def test_unknown_university_type_is_rejected(session):
    with pytest.raises(IntegrityError, match="ck_university_type"):
        session.add(
            University(name="X", city="Y", type="school", website="https://example.org")
        )
        session.flush()
