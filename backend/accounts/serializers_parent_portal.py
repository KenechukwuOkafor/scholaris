"""
Serializers for the Parent Portal API.
"""

from rest_framework import serializers

from academics.models import ReportCardFile
from enrollment.models import AttendanceRecord, Parent, Student
from finance.models import StudentInvoice
from notifications.models import Notification


class ParentProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parent
        fields = ["id", "name", "phone", "email", "created_at"]


class StudentBriefSerializer(serializers.ModelSerializer):
    """
    Compact student representation shown in a parent's child list.
    Includes the relationship label from the StudentParent link.
    """

    student_class = serializers.StringRelatedField()
    relationship = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id",
            "registration_number",
            "first_name",
            "last_name",
            "gender",
            "status",
            "student_class",
            "relationship",
        ]

    def get_relationship(self, obj) -> str:
        # The view annotates each student with the relationship string.
        return getattr(obj, "_relationship", "")


class ReportCardFileSerializer(serializers.ModelSerializer):
    term = serializers.StringRelatedField()
    pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = ReportCardFile
        fields = ["id", "term", "pdf_url", "generated_at"]

    def get_pdf_url(self, obj) -> str:
        request = self.context.get("request")
        if obj.pdf_file and request:
            return request.build_absolute_uri(obj.pdf_file.url)
        return obj.pdf_file.url if obj.pdf_file else ""


class AttendanceRecordSerializer(serializers.ModelSerializer):
    date = serializers.DateField(source="session.date")
    school_class = serializers.StringRelatedField(source="session.school_class")
    status_display = serializers.CharField(source="get_status_display")

    class Meta:
        model = AttendanceRecord
        fields = ["id", "date", "school_class", "status", "status_display"]


class StudentInvoiceSerializer(serializers.ModelSerializer):
    term = serializers.StringRelatedField()
    status_display = serializers.CharField(source="get_status_display")

    class Meta:
        model = StudentInvoice
        fields = [
            "id",
            "term",
            "amount_due",
            "amount_paid",
            "balance",
            "status",
            "status_display",
            "created_at",
        ]


class ParentNotificationSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_type_display")

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "message",
            "type",
            "type_display",
            "is_read",
            "created_at",
        ]
