"""
End-to-end test script for the report card and bulk class PDF engine.

Run with:
    python test_report_card_e2e.py
"""

import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scholaris.settings.dev")
django.setup()

# ---------------------------------------------------------------------------
# Imports (after django.setup)
# ---------------------------------------------------------------------------
import datetime
from decimal import Decimal

from django.db import connection, reset_queries
from django.test.utils import override_settings
from rest_framework.exceptions import NotFound

from core.models import School, SchoolClass, Session, Subject, Term
from enrollment.models import Student
from academics.models import (
    AssessmentType,
    Score,
    ResultSummary,
    ResultStatistics,
    StudentSubjectResult,
    TraitCategory,
    Trait,
    TraitScale,
    StudentTraitRating,
)
from academics.services.result_processor import ResultProcessor
from academics.services.reportcard_service import generate_report_card
from academics.services.reportcard_pdf_service import generate_report_card_pdf
from academics.services.class_report_pdf_service import generate_class_report_pdf

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

results = []

def check(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def get_or_create_school(name, slug):
    return School.objects.get_or_create(
        slug=slug,
        defaults=dict(name=name, school_type="secondary", email=f"{slug}@test.com"),
    )[0]


def cleanup(school):
    """Remove all data for a school so seeds are idempotent."""
    StudentTraitRating.objects.filter(school=school).delete()
    StudentSubjectResult.objects.filter(school=school).delete()
    ResultSummary.objects.filter(school=school).delete()
    ResultStatistics.objects.filter(school=school).delete()
    Score.objects.filter(school=school).delete()
    AssessmentType.objects.filter(school=school).delete()
    Student.objects.filter(school=school).delete()
    SchoolClass.objects.filter(school=school).delete()
    Subject.objects.filter(school=school).delete()
    Term.objects.filter(school=school).delete()
    Session.objects.filter(school=school).delete()
    TraitScale.objects.filter(school=school).delete()
    Trait.objects.filter(school=school).delete()
    TraitCategory.objects.filter(school=school).delete()


# ---------------------------------------------------------------------------
# 1. Migrations
# ---------------------------------------------------------------------------

print("\n=== 1. Migrations ===")
from django.db import connection
tables = connection.introspection.table_names()
required = [
    "academics_traitcategory",
    "academics_trait",
    "academics_traitscale",
    "academics_studenttraitrating",
]
for t in required:
    check(f"Table {t} exists", t in tables)

# ---------------------------------------------------------------------------
# 2. Seed data
# ---------------------------------------------------------------------------

print("\n=== 2. Seeding test data ===")

alpha = get_or_create_school("Alpha School", "alpha-school")
beta  = get_or_create_school("Beta School",  "beta-school")
cleanup(alpha)
cleanup(beta)

# Session + Term for Alpha
session = Session.objects.create(
    school=alpha, name="2025/2026",
    start_date=datetime.date(2025, 9, 1),
    end_date=datetime.date(2026, 7, 31),
)
term = Term.objects.create(
    school=alpha, session=session,
    term_number=Term.TermNumber.FIRST,
    start_date=datetime.date(2025, 9, 1),
    end_date=datetime.date(2025, 12, 20),
)

# Class
jss1 = SchoolClass.objects.create(school=alpha, name="JSS1", order=1)

# Subjects
maths   = Subject.objects.create(school=alpha, name="Mathematics", code="MTH")
english = Subject.objects.create(school=alpha, name="English Language", code="ENG")
science = Subject.objects.create(school=alpha, name="Basic Science", code="SCI")

# Assessment types (weights must sum to 100)
ca1  = AssessmentType(school=alpha, term=term, name="CA1",  weight=20, order=1)
ca1.max_score = 20; ca1.save()
ca2  = AssessmentType(school=alpha, term=term, name="CA2",  weight=20, order=2)
ca2.max_score = 20; ca2.save()
exam = AssessmentType(school=alpha, term=term, name="Exam", weight=60, order=3)
exam.max_score = 60; exam.save()

# 3 students
def make_student(n):
    return Student.objects.create(
        school=alpha, student_class=jss1,
        registration_number=f"2025/JSS1/{n:03d}",
        first_name=f"Student{n}", last_name="Alpha",
        gender=Student.Gender.MALE,
        status=Student.Status.ACTIVE,
    )

students = [make_student(i) for i in range(1, 4)]

# Score matrix: {student_index: {subject: {ca1, ca2, exam}}}
score_data = [
    {maths: (18, 17, 55), english: (15, 16, 50), science: (20, 18, 58)},
    {maths: (20, 19, 58), english: (18, 17, 55), science: (16, 15, 52)},
    {maths: (14, 15, 48), english: (12, 13, 42), science: (13, 14, 45)},
]

for student, subj_map in zip(students, score_data):
    for subject, (s1, s2, se) in subj_map.items():
        for atype, val in [(ca1, s1), (ca2, s2), (exam, se)]:
            Score.objects.create(
                school=alpha, student=student, subject=subject,
                term=term, assessment_type=atype, score=Decimal(str(val)),
            )

check("3 students created", Student.objects.filter(school=alpha).count() == 3)
check("Score rows created", Score.objects.filter(school=alpha).count() == 27,
      f"found {Score.objects.filter(school=alpha).count()}")

# Run result processor
from django.db import transaction
with transaction.atomic():
    result = ResultProcessor().process_results(school_class=jss1, term=term)

check("ResultProcessor ran", result["students_processed"] == 3,
      str(result))
check("StudentSubjectResult rows",
      StudentSubjectResult.objects.filter(school=alpha).count() == 9)
check("ResultSummary rows",
      ResultSummary.objects.filter(school=alpha).count() == 3)
check("ResultStatistics rows",
      ResultStatistics.objects.filter(school=alpha).count() == 3)

# Trait seed
affective = TraitCategory.objects.create(school=alpha, name="Affective Traits", display_order=1)
psycho    = TraitCategory.objects.create(school=alpha, name="Psychomotor Skills", display_order=2)

punctuality = Trait.objects.create(school=alpha, category=affective, name="Punctuality", display_order=1)
behaviour   = Trait.objects.create(school=alpha, category=affective, name="Behaviour",   display_order=2)
handwriting = Trait.objects.create(school=alpha, category=psycho,    name="Handwriting",  display_order=1)

excellent  = TraitScale.objects.create(school=alpha, label="Excellent",  numeric_value=5, display_order=1)
very_good  = TraitScale.objects.create(school=alpha, label="Very Good",  numeric_value=4, display_order=2)
good       = TraitScale.objects.create(school=alpha, label="Good",       numeric_value=3, display_order=3)

student1 = students[0]
for trait, scale in [(punctuality, excellent), (behaviour, very_good), (handwriting, good)]:
    StudentTraitRating.objects.create(
        school=alpha, student=student1, term=term, trait=trait, scale=scale,
    )

check("Trait ratings created",
      StudentTraitRating.objects.filter(school=alpha, student=student1).count() == 3)

# ---------------------------------------------------------------------------
# 3. Single report card
# ---------------------------------------------------------------------------

print("\n=== 3. Single report card ===")

report = generate_report_card(student1, term)

check("student_info present",   "student_info" in report)
check("summary present",        "summary" in report)
check("subjects present",       "subjects" in report)
check("traits present",         "traits" in report)
check("3 subjects returned",    len(report["subjects"]) == 3)
check("session name present",   report["student_info"]["session"] == "2025/2026")
check("class position present", report["summary"]["class_position"] is not None)
check("students_in_class == 3", report["summary"]["students_in_class"] == 3)

# Verify total scores match DB
for subj_row in report["subjects"]:
    db_row = StudentSubjectResult.objects.get(
        school=alpha, student=student1, term=term, subject__name=subj_row["subject"]
    )
    check(
        f"Total score correct for {subj_row['subject']}",
        subj_row["total_score"] == db_row.total_score,
        f"{subj_row['total_score']} == {db_row.total_score}",
    )

# Assessment columns dynamic
first_subj = report["subjects"][0]
check("Assessment keys dynamic",
      set(first_subj["assessments"].keys()) == {"CA1", "CA2", "Exam"})

# Stats present
check("class_average present",  first_subj["class_average"] is not None)
check("highest present",        first_subj["highest"] is not None)
check("lowest present",         first_subj["lowest"] is not None)

# Grade mapping
for subj_row in report["subjects"]:
    total = subj_row["total_score"]
    grade = subj_row["grade"]
    if   total >= 70: expected = "A"
    elif total >= 60: expected = "B"
    elif total >= 50: expected = "C"
    elif total >= 40: expected = "D"
    else:             expected = "F"
    check(f"Grade correct for {subj_row['subject']} ({total}→{grade})", grade == expected)

# Traits grouped
check("Traits grouped by category", "Affective Traits" in report["traits"])
check("Affective Traits count == 2",
      len(report["traits"].get("Affective Traits", [])) == 2)
check("Psychomotor Skills count == 1",
      len(report["traits"].get("Psychomotor Skills", [])) == 1)
check("Trait rating value correct",
      report["traits"]["Affective Traits"][0]["rating"] == "Excellent")

# NotFound for missing results
print("\n  → NotFound for student with no results:")
orphan = Student.objects.create(
    school=alpha, student_class=jss1,
    registration_number="ORPHAN001",
    first_name="Orphan", last_name="Alpha",
    gender=Student.Gender.MALE,
    status=Student.Status.ACTIVE,
)
try:
    generate_report_card(orphan, term)
    check("NotFound raised for missing results", False)
except NotFound:
    check("NotFound raised for missing results", True)

# ---------------------------------------------------------------------------
# 4. Single PDF
# ---------------------------------------------------------------------------

print("\n=== 4. Single PDF generation ===")

pdf = generate_report_card_pdf(student1, term)
check("PDF bytes returned",     isinstance(pdf, bytes))
check("PDF non-empty",          len(pdf) > 0)
check("PDF is valid PDF magic", pdf[:4] == b"%PDF", f"starts with {pdf[:4]}")
check("PDF size > 0",           len(pdf) > 0,
      f"{len(pdf):,} bytes")

# ---------------------------------------------------------------------------
# 5. Bulk class PDF
# ---------------------------------------------------------------------------

print("\n=== 5. Bulk class PDF ===")

bulk_pdf = generate_class_report_pdf(school_class=jss1, term=term)
check("Bulk PDF bytes returned",  isinstance(bulk_pdf, bytes))
check("Bulk PDF non-empty",       len(bulk_pdf) > 0)
check("Bulk PDF valid magic",     bulk_pdf[:4] == b"%PDF")
check("Bulk PDF larger than single PDF", len(bulk_pdf) > len(pdf),
      f"bulk={len(bulk_pdf):,} single={len(pdf):,}")

# ---------------------------------------------------------------------------
# 6. Page breaks in template
# ---------------------------------------------------------------------------

print("\n=== 6. Page break verification ===")

from django.template.loader import render_to_string
from academics.services.class_report_pdf_service import _TEMPLATE as CLASS_TEMPLATE

reports_data = [generate_report_card(s, term) for s in students]
html = render_to_string(CLASS_TEMPLATE, {"reports": reports_data})

check("page-break-after in HTML",       "page-break-after: always" in html)
check("report-card class in HTML",      'class="report-card"' in html)
check("HTML contains all student names",
      all(f"Student{i+1}" in html for i in range(3)))

# ---------------------------------------------------------------------------
# 7. Tenant isolation
# ---------------------------------------------------------------------------

print("\n=== 7. Tenant isolation ===")

# Beta school with its own class but no results seeded
beta_session = Session.objects.create(
    school=beta, name="2025/2026",
    start_date=datetime.date(2025, 9, 1),
    end_date=datetime.date(2026, 7, 31),
)
beta_term = Term.objects.create(
    school=beta, session=beta_session,
    term_number=Term.TermNumber.FIRST,
    start_date=datetime.date(2025, 9, 1),
    end_date=datetime.date(2025, 12, 20),
)
beta_class = SchoolClass.objects.create(school=beta, name="JSS1", order=1)

# generate_class_report_pdf with a class that has no results
try:
    generate_class_report_pdf(school_class=beta_class, term=beta_term)
    check("NotFound for class with no results", False)
except NotFound as e:
    check("NotFound for class with no results", True, str(e))

# Cross-school: student from Alpha, class from Beta — score query scoped to student.school
# The service fetches students via school_class.school, so a Beta class never yields Alpha students
beta_students = list(
    Student.objects.for_school(beta).filter(student_class=beta_class)
)
check("No Alpha students returned for Beta class", len(beta_students) == 0)

# generate_report_card for alpha student with beta term → NotFound (no results)
try:
    generate_report_card(student1, beta_term)
    check("NotFound for student+wrong-school term", False)
except NotFound:
    check("NotFound for student+wrong-school term", True)

# ---------------------------------------------------------------------------
# 8. Query count
# ---------------------------------------------------------------------------

print("\n=== 8. Query count ===")

# Reload student with fresh cache
student_fresh = Student.objects.select_related("school").get(pk=student1.pk)
term_fresh = Term.objects.select_related("session").get(pk=term.pk)

from django.conf import settings
settings.DEBUG = True
reset_queries()

_ = generate_report_card(student_fresh, term_fresh)
q_count = len(connection.queries)
check(f"generate_report_card queries <= 5 (got {q_count})", q_count <= 5)

reset_queries()
_ = generate_class_report_pdf(school_class=jss1, term=term_fresh)
bulk_q = len(connection.queries)
# 1 student fetch + (5 per student × 3 students) = 16 max, but subqueries optimise this
check(f"generate_class_report_pdf queries reasonable (got {bulk_q})",
      bulk_q <= 17,  # 1 student query + 5 per student (×3) + 1 for orphan (NotFound early exit)
      f"{bulk_q} queries for 3 students + 1 orphan")

# ---------------------------------------------------------------------------
# Final report table
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"{'Check':<50} {'Result'}")
print("-" * 60)
for name, status, *detail in results:
    d = detail[0] if detail else ""
    indicator = "✓" if status == "PASS" else "✗"
    print(f"  {indicator} {name:<48} {status}" + (f"  ({d})" if d else ""))

passed = sum(1 for _, s, *_ in results if s == "PASS")
failed = sum(1 for _, s, *_ in results if s == "FAIL")
print("-" * 60)
print(f"  Total: {passed} passed, {failed} failed")
print("=" * 60)

if failed:
    sys.exit(1)
