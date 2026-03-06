from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import BroadsheetSubmitSerializer
from .services.broadsheet_service import BroadsheetService


class BroadsheetSubmitView(APIView):
    """
    POST /api/academics/broadsheet/submit/

    Submit scores for an entire class in one request (broadsheet entry).

    The authenticated teacher must have a TeachingAssignment for the
    specified class + subject combination at their school.

    The school is derived from the submitted class_id, so no school_id
    field is required in the payload.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = BroadsheetSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Resolve school from the class.  This is done inside the service
        # to keep the view thin, but we need the school object here to
        # pass into the transaction boundary.
        from core.models import SchoolClass
        from rest_framework.exceptions import NotFound

        try:
            school_class = SchoolClass.objects.select_related("school").get(
                id=data["class_id"]
            )
        except SchoolClass.DoesNotExist:
            raise NotFound(f"Class {data['class_id']} not found.")

        school = school_class.school

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
