"""
ClassReportPDFService — generates a single PDF containing report cards
for every student in a class.

Each student is rendered on its own page. Students without computed results
(i.e. generate_report_card raises NotFound) are silently skipped so that one
missing result set does not abort the entire class PDF.
"""

from __future__ import annotations

from django.template.loader import render_to_string
from rest_framework.exceptions import NotFound
from weasyprint import HTML

from academics.services.reportcard_service import generate_report_card
from core.models import SchoolClass, Term
from enrollment.models import Student

_TEMPLATE = "reportcards/class_report.html"


def generate_class_report_pdf(school_class: SchoolClass, term: Term) -> bytes:
    """
    Build a single PDF containing one report card per student in *school_class*
    for *term*.

    Steps:
        1. Fetch all students in the class via tenant-scoped query.
        2. Call generate_report_card() for each student, skipping any whose
           results have not yet been computed.
        3. Render all reports into a single HTML document.
        4. Convert HTML → PDF via WeasyPrint and return raw bytes.

    Returns:
        Raw PDF bytes.

    Raises:
        NotFound — if no students in the class have computed results
        (every student was skipped).
    """
    school = school_class.school

    students = (
        Student.objects
        .for_school(school)
        .filter(student_class=school_class)
        .select_related("school")  # pre-load school so generate_report_card doesn't N+1
    )

    reports = []
    for student in students:
        try:
            reports.append(generate_report_card(student, term))
        except NotFound:
            # Results not yet computed for this student — skip gracefully.
            continue

    if not reports:
        raise NotFound(
            f"No computed results found for any student in "
            f"'{school_class.name}' for term '{term}'. "
            "Run result processing first."
        )

    html = render_to_string(_TEMPLATE, {"reports": reports})

    return HTML(string=html).write_pdf()
