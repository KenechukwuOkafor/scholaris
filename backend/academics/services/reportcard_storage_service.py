"""
ReportCardStorageService — persist and retrieve generated report card PDFs.
"""

from __future__ import annotations

from django.core.files.base import ContentFile
from rest_framework.exceptions import NotFound

from academics.models import ReportCardFile
from core.models import Term
from enrollment.models import Student


def store_report_card(student: Student, term: Term, pdf_bytes: bytes) -> ReportCardFile:
    """
    Save *pdf_bytes* to disk and create-or-update the ReportCardFile row.

    The file is named ``<student_id>_<term_id>.pdf`` inside the
    ``reportcards/`` upload directory.  If a file already exists for this
    (student, term) pair the old file is replaced and generated_at is reset.

    Args:
        student:   the student the report card belongs to.
        term:      the term the report card covers.
        pdf_bytes: raw PDF bytes returned by generate_report_card_pdf().

    Returns:
        The saved (or updated) ReportCardFile instance.
    """
    filename = f"{student.id}_{term.id}.pdf"
    file_content = ContentFile(pdf_bytes, name=filename)

    try:
        record = ReportCardFile.objects.get(student=student, term=term)
        # Delete the old file from storage before replacing it.
        record.pdf_file.delete(save=False)
        record.pdf_file = file_content
        record.save(update_fields=["pdf_file", "updated_at"])
    except ReportCardFile.DoesNotExist:
        record = ReportCardFile.objects.create(
            school=student.school,
            student=student,
            term=term,
            pdf_file=file_content,
        )

    return record


def get_report_card(student: Student, term: Term) -> ReportCardFile:
    """
    Retrieve the stored ReportCardFile for *student* in *term*.

    Args:
        student: the student whose report card is requested.
        term:    the term to retrieve.

    Returns:
        The ReportCardFile instance with a valid pdf_file field.

    Raises:
        rest_framework.exceptions.NotFound — when no stored file exists for
        this student/term combination.
    """
    try:
        return ReportCardFile.objects.get(student=student, term=term)
    except ReportCardFile.DoesNotExist:
        raise NotFound(
            f"No stored report card found for {student} in {term}. "
            "Generate it first via the PDF endpoint."
        )
