from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.tenant import get_request_school

from .services.dashboard_service import get_school_overview


class SchoolDashboardView(APIView):
    """
    GET /api/analytics/dashboard/

    Returns a school-wide metrics snapshot for the authenticated user's school.

    Response body:
        {
            "students":         <int>,
            "teachers":         <int>,
            "attendance_today": <float>,   // percentage, e.g. 87.5
            "fees_collected":   <string>,  // decimal string, e.g. "4250000.00"
            "outstanding_fees": <string>
        }

    Tenant isolation: all queries are scoped to get_request_school(request).
    Query count: 4 — no N+1.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        school = get_request_school(request)
        data = get_school_overview(school)
        return Response(data)
