from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import SchoolClass
from core.tenant import get_request_school

from .models import AttendanceSession, Parent, Student
from .serializers import (
    AttendanceSessionSerializer,
    CreateParentSerializer,
    LinkParentSerializer,
    MarkAttendanceSerializer,
    ParentSerializer,
    StartSessionSerializer,
    StudentParentSerializer,
)
from .services.attendance_service import mark_attendance, start_attendance_session
from .services.parent_service import create_parent, link_parent


class StartAttendanceSessionView(APIView):
    """
    POST /api/enrollment/attendance/start/

    Open a new attendance session for a class on a given date.

    Request body:
        {
            "class_id": "<uuid>",
            "date":     "YYYY-MM-DD"
        }

    Returns the created AttendanceSession.
    Raises 400 if a session already exists for this class on this date.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = StartSessionSerializer(data=request.data)
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
            raise PermissionDenied("The requested class does not belong to your school.")

        session = start_attendance_session(
            school_class=school_class,
            date=data["date"],
            user=request.user,
        )

        return Response(AttendanceSessionSerializer(session).data, status=201)


class MarkAttendanceView(APIView):
    """
    POST /api/enrollment/attendance/mark/

    Record attendance statuses for students in an existing session.

    Request body:
        {
            "session_id": "<uuid>",
            "records": [
                {"student_id": "<uuid>", "status": "present"},
                {"student_id": "<uuid>", "status": "absent"},
                {"student_id": "<uuid>", "status": "late"}
            ]
        }

    Idempotent — re-submitting overwrites previous statuses for the same students.
    Returns the number of records saved.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = MarkAttendanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user_school = get_request_school(request)

        try:
            session = AttendanceSession.objects.select_related(
                "school_class__school"
            ).get(id=data["session_id"])
        except AttendanceSession.DoesNotExist:
            raise NotFound(f"Attendance session {data['session_id']} not found.")

        school = session.school

        if user_school is not None and user_school != school:
            raise PermissionDenied("This session does not belong to your school.")

        result = mark_attendance(session=session, records=data["records"])

        return Response(
            {
                "message": "Attendance recorded successfully.",
                "records_saved": result["records_saved"],
            }
        )


class CreateParentView(APIView):
    """
    POST /api/enrollment/parents/create/

    Create a new parent and immediately link them to a student.

    Request body:
        {
            "student_id":   "<uuid>",
            "name":         "Jane Doe",
            "phone":        "+2348012345678",
            "relationship": "Mother",
            "email":        "jane@example.com"   // optional
        }

    Returns the created Parent and StudentParent link.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = CreateParentSerializer(data=request.data)
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

        parent, link = create_parent(
            student=student,
            name=data["name"],
            phone=data["phone"],
            relationship=data["relationship"],
            email=data.get("email", ""),
        )

        return Response(
            {
                "parent": ParentSerializer(parent).data,
                "link": StudentParentSerializer(link).data,
            },
            status=201,
        )


class LinkParentView(APIView):
    """
    POST /api/enrollment/parents/link/

    Link an existing parent to a student.

    Request body:
        {
            "student_id":   "<uuid>",
            "parent_id":    "<uuid>",
            "relationship": "Guardian"
        }

    Returns the created StudentParent link.
    Raises 400 if the link already exists or schools differ.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = LinkParentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user_school = get_request_school(request)

        try:
            student = Student.objects.select_related("school").get(
                id=data["student_id"]
            )
        except Student.DoesNotExist:
            raise NotFound(f"Student {data['student_id']} not found.")

        try:
            parent = Parent.objects.select_related("school").get(
                id=data["parent_id"]
            )
        except Parent.DoesNotExist:
            raise NotFound(f"Parent {data['parent_id']} not found.")

        if user_school is not None and user_school != student.school:
            raise PermissionDenied("This student does not belong to your school.")

        link = link_parent(
            student=student,
            parent=parent,
            relationship=data["relationship"],
        )

        return Response(StudentParentSerializer(link).data, status=201)
