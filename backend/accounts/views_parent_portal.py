"""
Parent Portal API views.

Authentication flow:
    POST /api/parent/login/
        Body:  { "phone": "+2348012345678", "school_slug": "demo-school" }
        Returns: { "access": "...", "refresh": "...", "parent": {...} }

    All other endpoints require:
        Authorization: Bearer <access_token>

Tenant safety:
    Every queryset is scoped with .objects.for_school(parent.school).
    Student ownership is verified via StudentParent before returning data.
"""

from __future__ import annotations

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from academics.models import ReportCardFile
from core.models import School, Term
from enrollment.models import AttendanceRecord, Parent, Student, StudentParent
from finance.models import StudentInvoice
from notifications.models import Notification

from .serializers_parent_portal import (
    AttendanceRecordSerializer,
    ParentNotificationSerializer,
    ParentProfileSerializer,
    ReportCardFileSerializer,
    StudentBriefSerializer,
    StudentInvoiceSerializer,
)


# ---------------------------------------------------------------------------
# Auth infrastructure
# ---------------------------------------------------------------------------


class ParentUser:
    """
    Lightweight wrapper that makes a Parent look like a Django user to DRF.
    Not a database model — exists only within the request lifecycle.
    """

    is_authenticated = True
    is_active = True
    is_staff = False
    is_superuser = False
    is_anonymous = False

    def __init__(self, parent: Parent) -> None:
        self.parent = parent
        self.id = parent.id

    def __str__(self) -> str:
        return self.parent.name


class ParentJWTAuthentication(BaseAuthentication):
    """
    Validates a JWT that carries a ``parent_id`` claim.

    Tokens are issued by ParentLoginView using SimpleJWT's RefreshToken
    infrastructure with a custom ``parent_id`` payload field.
    If the Authorization header is absent or the token has no ``parent_id``,
    authentication is skipped (returns None) so other backends can run.
    """

    def authenticate(self, request: Request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return None

        raw_token = auth_header.split(" ", 1)[1]

        try:
            from rest_framework_simplejwt.tokens import AccessToken
            token = AccessToken(raw_token)
        except TokenError:
            return None

        parent_id = token.get("parent_id")
        if not parent_id:
            # Not a parent token; let other auth backends handle it.
            return None

        try:
            parent = Parent.objects.select_related("school").get(id=parent_id)
        except Parent.DoesNotExist:
            raise AuthenticationFailed("Parent account not found.")

        return (ParentUser(parent), token)


class IsAuthenticatedParent(BasePermission):
    """Allows access only to requests authenticated as a Parent."""

    message = "Parent authentication required."

    def has_permission(self, request: Request, view) -> bool:
        return isinstance(request.user, ParentUser)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_student_for_parent(request: Request, parent: Parent, school) -> Student:
    """
    Resolve the student_id query param and verify that the student is
    linked to the requesting parent at the same school.

    Raises NotFound if:
      - student_id param is missing
      - student is not linked to this parent
    """
    student_id = request.query_params.get("student_id", "").strip()
    if not student_id:
        raise ValidationError({"student_id": "This parameter is required."})

    sp = (
        StudentParent.objects.for_school(school)
        .filter(parent=parent, student_id=student_id)
        .select_related("student__school", "student__student_class")
        .first()
    )
    if sp is None:
        raise NotFound("Student not found.")

    return sp.student


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


class ParentLoginView(APIView):
    """
    POST /api/parent/login/

    Issue a JWT access+refresh pair for a parent identified by their
    phone number at a specific school.

    Request body:
        {
            "phone":       "+2348012345678",
            "school_slug": "greenfield-academy"
        }

    Returns:
        {
            "access":  "<JWT>",
            "refresh": "<JWT>",
            "parent":  { "id", "name", "phone", "email" }
        }

    No prior authentication is required.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        phone = (request.data.get("phone") or "").strip()
        school_slug = (request.data.get("school_slug") or "").strip()

        if not phone or not school_slug:
            raise ValidationError(
                {"detail": "'phone' and 'school_slug' are required."}
            )

        try:
            school = School.objects.get(
                slug=school_slug, status=School.Status.ACTIVE
            )
        except School.DoesNotExist:
            raise AuthenticationFailed("Invalid credentials.")

        try:
            parent = Parent.objects.for_school(school).get(phone=phone)
        except Parent.DoesNotExist:
            raise AuthenticationFailed("Invalid credentials.")

        # Build token pair with parent claims.
        refresh = RefreshToken()
        refresh["parent_id"] = str(parent.id)
        refresh["school_id"] = str(parent.school_id)

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "parent": {
                    "id": str(parent.id),
                    "name": parent.name,
                    "phone": parent.phone,
                    "email": parent.email,
                },
            }
        )


# ---------------------------------------------------------------------------
# Portal endpoints
# ---------------------------------------------------------------------------


class ParentProfileView(APIView):
    """
    GET /api/parent/profile/

    Return the authenticated parent's profile.
    """

    authentication_classes = [ParentJWTAuthentication]
    permission_classes = [IsAuthenticatedParent]

    def get(self, request: Request) -> Response:
        parent = request.user.parent
        serializer = ParentProfileSerializer(parent)
        return Response(serializer.data)


class ParentStudentsView(APIView):
    """
    GET /api/parent/students/

    Return all students linked to the authenticated parent via StudentParent.
    Each student record includes the relationship label (e.g. "Mother").
    """

    authentication_classes = [ParentJWTAuthentication]
    permission_classes = [IsAuthenticatedParent]

    def get(self, request: Request) -> Response:
        parent = request.user.parent
        school = parent.school

        links = (
            StudentParent.objects.for_school(school)
            .filter(parent=parent)
            .select_related(
                "student__school",
                "student__student_class",
            )
        )

        students = []
        for sp in links:
            sp.student._relationship = sp.relationship
            students.append(sp.student)

        serializer = StudentBriefSerializer(
            students, many=True, context={"request": request}
        )
        return Response(serializer.data)


class ParentReportCardsView(APIView):
    """
    GET /api/parent/reportcards/?student_id=<uuid>

    Return all stored report card PDFs for one of the parent's children.
    Results are ordered most-recent first.
    """

    authentication_classes = [ParentJWTAuthentication]
    permission_classes = [IsAuthenticatedParent]

    def get(self, request: Request) -> Response:
        parent = request.user.parent
        school = parent.school

        student = _resolve_student_for_parent(request, parent, school)

        report_cards = (
            ReportCardFile.objects.for_school(school)
            .filter(student=student)
            .select_related("term")
            .order_by("-generated_at")
        )

        serializer = ReportCardFileSerializer(
            report_cards, many=True, context={"request": request}
        )
        return Response(serializer.data)


class ParentAttendanceView(APIView):
    """
    GET /api/parent/attendance/?student_id=<uuid>&term=<uuid>

    Return attendance records for one of the parent's children within a
    given term.  Records are ordered by session date ascending.

    The term param is the UUID of a Term within the parent's school.
    Date-range filtering is used so attendance sessions do not need a
    direct term FK.
    """

    authentication_classes = [ParentJWTAuthentication]
    permission_classes = [IsAuthenticatedParent]

    def get(self, request: Request) -> Response:
        parent = request.user.parent
        school = parent.school

        student = _resolve_student_for_parent(request, parent, school)

        term_id = request.query_params.get("term", "").strip()
        if not term_id:
            raise ValidationError({"term": "This parameter is required."})

        try:
            term = Term.objects.for_school(school).get(id=term_id)
        except Term.DoesNotExist:
            raise NotFound("Term not found.")

        records = (
            AttendanceRecord.objects.for_school(school)
            .filter(
                student=student,
                session__date__gte=term.start_date,
                session__date__lte=term.end_date,
            )
            .select_related("session__school_class")
            .order_by("session__date")
        )

        serializer = AttendanceRecordSerializer(records, many=True)
        return Response(
            {
                "term": str(term),
                "student": f"{student.first_name} {student.last_name}",
                "total": records.count(),
                "records": serializer.data,
            }
        )


class ParentFeesView(APIView):
    """
    GET /api/parent/fees/?student_id=<uuid>

    Return all invoices for one of the parent's children, most recent first.
    """

    authentication_classes = [ParentJWTAuthentication]
    permission_classes = [IsAuthenticatedParent]

    def get(self, request: Request) -> Response:
        parent = request.user.parent
        school = parent.school

        student = _resolve_student_for_parent(request, parent, school)

        invoices = (
            StudentInvoice.objects.for_school(school)
            .filter(student=student)
            .select_related("term")
            .order_by("-created_at")
        )

        serializer = StudentInvoiceSerializer(invoices, many=True)
        return Response(serializer.data)


class ParentNotificationsView(APIView):
    """
    GET /api/parent/notifications/

    Return notifications addressed to the authenticated parent.
    Supports optional ?unread_only=true query param.
    """

    authentication_classes = [ParentJWTAuthentication]
    permission_classes = [IsAuthenticatedParent]

    def get(self, request: Request) -> Response:
        parent = request.user.parent
        school = parent.school

        qs = (
            Notification.objects.for_school(school)
            .filter(recipient_parent=parent)
            .order_by("-created_at")
        )

        if request.query_params.get("unread_only", "").lower() == "true":
            qs = qs.filter(is_read=False)

        serializer = ParentNotificationSerializer(qs, many=True)
        return Response(serializer.data)
