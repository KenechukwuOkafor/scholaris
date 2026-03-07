from django.db import transaction
from django.http import HttpResponse
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import SchoolClass, Term
from core.tenant import get_request_school

from .serializers import BroadsheetSubmitSerializer
from .services.broadsheet_service import BroadsheetService
from .services.class_report_pdf_service import generate_class_report_pdf


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
