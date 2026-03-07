from rest_framework import serializers

from .models import AttendanceRecord, AttendanceSession, Parent, StudentParent


# ---------------------------------------------------------------------------
# Input serializers (request validation)
# ---------------------------------------------------------------------------


class AttendanceRecordInputSerializer(serializers.Serializer):
    student_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=AttendanceRecord.Status.choices)


class StartSessionSerializer(serializers.Serializer):
    class_id = serializers.UUIDField()
    date = serializers.DateField()


class MarkAttendanceSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    records = AttendanceRecordInputSerializer(many=True, allow_empty=False)


# ---------------------------------------------------------------------------
# Output serializers (response representation)
# ---------------------------------------------------------------------------


class AttendanceSessionSerializer(serializers.ModelSerializer):
    school_class = serializers.StringRelatedField()
    marked_by = serializers.StringRelatedField()

    class Meta:
        model = AttendanceSession
        fields = ["id", "school_class", "date", "marked_by", "created_at"]


class AttendanceRecordSerializer(serializers.ModelSerializer):
    student = serializers.StringRelatedField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = ["id", "student", "status", "status_display"]


# ---------------------------------------------------------------------------
# Parent serializers
# ---------------------------------------------------------------------------


class CreateParentSerializer(serializers.Serializer):
    student_id = serializers.UUIDField()
    name = serializers.CharField(max_length=200)
    phone = serializers.CharField(max_length=20)
    relationship = serializers.CharField(max_length=100)
    email = serializers.EmailField(required=False, allow_blank=True, default="")


class LinkParentSerializer(serializers.Serializer):
    student_id = serializers.UUIDField()
    parent_id = serializers.UUIDField()
    relationship = serializers.CharField(max_length=100)


class ParentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parent
        fields = ["id", "name", "phone", "email", "created_at"]


class StudentParentSerializer(serializers.ModelSerializer):
    parent = ParentSerializer(read_only=True)
    relationship = serializers.CharField()

    class Meta:
        model = StudentParent
        fields = ["id", "parent", "relationship", "created_at"]
