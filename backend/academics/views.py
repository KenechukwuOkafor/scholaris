from django.db import transaction
from django.http import HttpResponse
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import SchoolClass, Term
from core.tenant import get_request_school
from enrollment.models import Student

from .serializers import (
    BroadsheetSubmitSerializer,
    ReportCardDownloadSerializer,
    ResultReleaseActionSerializer,
)
from .services.broadsheet_service import BroadsheetService
from .services.class_report_pdf_service import generate_class_report_pdf
from .services.reportcard_storage_service import get_report_card
from .services.result_release_service import publish_results, unpublish_results


class BroadsheetSubmitView(APIView):
    """
    POST /api/academics/broadsheet/submit/

    Submit scores for an entire class in one request (broadsheet entry).

    The authenticated teacher must have a TeachingAssignment for the
    specified class + subject combination at their school.

    Tenant isolation is enforced in two layers:
      1. get_request_school() binds the request to the user's school
         (raises PermissionDenied for non-staff users without a UserProfile).
      2. The school derived from class_id is cross-checked against the
         user's school; mismatches are rejected.

    Staff users (is_staff=True) without a UserProfile may operate across
    schools — intended for admin tooling only.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = BroadsheetSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # --- Tenant resolution ---------------------------------------------
        # user_school is the school bound to this user's profile, or None
        # for staff without a profile (admin fallback).
        user_school = get_request_school(request)

        # Derive school from the submitted class_id.
        try:
            school_class = SchoolClass.objects.select_related("school").get(
                id=data["class_id"]
            )
        except SchoolClass.DoesNotExist:
            raise NotFound(f"Class {data['class_id']} not found.")

        school = school_class.school

        # Cross-check: if the user has a profile, the class must belong to
        # their school — prevents submitting scores into another tenant.
        if user_school is not None and user_school != school:
            raise PermissionDenied(
                "The requested class does not belong to your school."
            )

        # --- Business logic ------------------------------------------------
        with transaction.atomic():
            result = BroadsheetService().submit_scores(
                user=request.user,
                school=school,
                class_id=data["class_id"],
                subject_id=data["subject_id"],
                term_id=data["term_id"],
                assessment_type_id=data["assessment_type_id"],
                score_entries=data["scores"],
            )

        return Response(
            {
                "message": "Scores saved successfully.",
                "students_updated": result["students_updated"],
            }
        )


class ClassReportCardPDFView(APIView):
    """
    GET /api/academics/report-card/class/<uuid:class_id>/<uuid:term_id>/

    Generate and stream a PDF containing one report card per student in the
    specified class for the given term.

    Tenant isolation is enforced via get_request_school():
      - Normal users must have a UserProfile; the class must belong to their school.
      - Staff users without a profile may access any school (admin fallback).

    Students without computed results are silently skipped.
    Returns 404 if no student in the class has any computed results.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, class_id, term_id) -> HttpResponse:
        user_school = get_request_school(request)

        # Resolve school_class and verify it exists.
        try:
            school_class = SchoolClass.objects.select_related("school").get(id=class_id)
        except SchoolClass.DoesNotExist:
            raise NotFound(f"Class {class_id} not found.")

        school = school_class.school

        # Tenant cross-check: non-staff users may only access their own school.
        if user_school is not None and user_school != school:
            raise PermissionDenied(
                "The requested class does not belong to your school."
            )

        # Resolve term within the same school.
        try:
            term = Term.objects.for_school(school).get(id=term_id)
        except Term.DoesNotExist:
            raise NotFound(f"Term {term_id} not found for school '{school.name}'.")

        pdf = generate_class_report_pdf(school_class=school_class, term=term)

        filename = (
            f"report_cards_{school_class.name}_{term.name}.pdf"
            .replace(" ", "_")
        )

        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response


class PublishResultsView(APIView):
    """
    POST /api/academics/results/publish/

    Publish computed results for a class+term, making report cards accessible.

    Request body:
        {
            "class_id": "<uuid>",
            "term_id":  "<uuid>"
        }

    Returns the updated release status.
    Tenant isolation: the class must belong to the requesting user's school.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = ResultReleaseActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user_school = get_request_school(request)

        try:
            school_class = SchoolClass.objects.select_related("school").get(
                id=data["class_id"]
            )
        except SchoolClass.DoesNotExist:
            raise NotFound(f"Class {data['class_id']} not found.")

        school = school_class.school

        if user_school is not None and user_school != school:
            raise PermissionDenied(
                "The requested class does not belong to your school."
            )

        try:
            term = Term.objects.for_school(school).get(id=data["term_id"])
        except Term.DoesNotExist:
            raise NotFound(f"Term {data['term_id']} not found for school '{school.name}'.")

        release = publish_results(school_class=school_class, term=term, actor=request.user)

        return Response(
            {
                "message": f"Results published for '{school_class.name}' — {term.name}.",
                "is_published": release.is_published,
                "published_at": release.published_at,
            }
        )


class UnpublishResultsView(APIView):
    """
    POST /api/academics/results/unpublish/

    Unpublish results for a class+term, hiding report cards.

    Request body:
        {
            "class_id": "<uuid>",
            "term_id":  "<uuid>"
        }

    Returns the updated release status.
    Tenant isolation: the class must belong to the requesting user's school.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = ResultReleaseActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user_school = get_request_school(request)

        try:
            school_class = SchoolClass.objects.select_related("school").get(
                id=data["class_id"]
            )
        except SchoolClass.DoesNotExist:
            raise NotFound(f"Class {data['class_id']} not found.")

        school = school_class.school

        if user_school is not None and user_school != school:
            raise PermissionDenied(
                "The requested class does not belong to your school."
            )

        try:
            term = Term.objects.for_school(school).get(id=data["term_id"])
        except Term.DoesNotExist:
            raise NotFound(f"Term {data['term_id']} not found for school '{school.name}'.")

        release = unpublish_results(school_class=school_class, term=term, actor=request.user)

        return Response(
            {
                "message": f"Results unpublished for '{school_class.name}' — {term.name}.",
                "is_published": release.is_published,
                "published_at": release.published_at,
            }
        )


class ReportCardDownloadView(APIView):
    """
    GET /api/academics/reportcard/download/?student_id=<uuid>&term_id=<uuid>

    Stream the stored PDF report card for a student in a term.

    The file must have been previously generated via the class report card
    endpoint (which auto-saves via store_report_card).  Returns 404 if no
    stored PDF exists yet.

    Tenant isolation: the student must belong to the requesting user's school.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> HttpResponse:
        serializer = ReportCardDownloadSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user_school = get_request_school(request)

        try:
            student = Student.objects.select_related("school").get(
                id=data["student_id"]
            )
        except Student.DoesNotExist:
            raise NotFound(f"Student {data['student_id']} not found.")

        if user_school is not None and user_school != student.school:
            raise PermissionDenied("This student does not belong to your school.")

        try:
            term = Term.objects.for_school(student.school).get(id=data["term_id"])
        except Term.DoesNotExist:
            raise NotFound(
                f"Term {data['term_id']} not found for school '{student.school.name}'."
            )

        record = get_report_card(student=student, term=term)

        filename = (
            f"report_card_{student.registration_number}_{term.name}.pdf"
            .replace(" ", "_")
        )

        response = HttpResponse(
            record.pdf_file.read(),
            content_type="application/pdf",
        )
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response
