"""
ReportCardPDFService — renders a student's report card to PDF bytes.

Template resolution order:
  1. ReportCardTemplate where is_active=True for the student's school
     (rendered via Django's Template engine from the stored HTML string).
  2. Fallback: filesystem template at templates/reportcards/report_card.html
     (rendered via render_to_string).

One extra DB query is made to look up the school's active template.
All other data comes from generate_report_card() with no additional queries.
"""

from __future__ import annotations

from django.template import Context, Template
from django.template.loader import render_to_string
from weasyprint import HTML

from academics.models import ReportCardTemplate
from academics.services.reportcard_service import generate_report_card
from core.models import Term
from enrollment.models import Student

_FALLBACK_TEMPLATE = "reportcards/report_card.html"


def _render_html(report_data: dict, school) -> str:
    """
    Resolve and render the HTML for a report card.

    Looks up the school's active ReportCardTemplate first.  If none exists,
    falls back to the default filesystem template.

    Args:
        report_data: structured dict from generate_report_card().
        school:      School instance (used for tenant-scoped template lookup).

    Returns:
        Rendered HTML string.
    """
    custom = (
        ReportCardTemplate.objects
        .for_school(school)
        .filter(is_active=True)
        .only("html_template")
        .first()
    )

    if custom:
        return Template(custom.html_template).render(Context({"report": report_data}))

    return render_to_string(_FALLBACK_TEMPLATE, {"report": report_data})


def generate_report_card_pdf(student: Student, term: Term) -> bytes:
    """
    Build a PDF report card for *student* in *term*.

    Steps:
        1. Fetch structured report data via generate_report_card().
        2. Resolve the school's active ReportCardTemplate; fall back to the
           default filesystem template if none is configured.
        3. Render HTML and convert to PDF bytes via WeasyPrint.

    Returns:
        Raw PDF bytes.

    Raises:
        rest_framework.exceptions.NotFound — propagated from generate_report_card()
        when no computed results exist for this student/term.
        django.template.TemplateSyntaxError — if the stored custom template
        contains invalid Django template syntax.
    """
    data = generate_report_card(student, term)

    html = _render_html(data, school=student.school)

    return HTML(string=html).write_pdf()
