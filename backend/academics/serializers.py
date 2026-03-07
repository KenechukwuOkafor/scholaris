from rest_framework import serializers


class ScoreEntrySerializer(serializers.Serializer):
    """A single student score entry in a broadsheet submission."""

    student_id = serializers.UUIDField()
    score = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0)


class BroadsheetSubmitSerializer(serializers.Serializer):
    """
    Payload for submitting scores for an entire class at once.

    Validation of business rules (teaching assignment, class membership,
    score ceiling) is deferred to BroadsheetService to keep serializers
    stateless and reusable.
    """

    class_id = serializers.UUIDField()
    subject_id = serializers.UUIDField()
    term_id = serializers.UUIDField()
    assessment_type_id = serializers.UUIDField()
    scores = ScoreEntrySerializer(many=True, min_length=1)

    def validate_scores(self, entries: list) -> list:
        student_ids = [e["student_id"] for e in entries]
        if len(student_ids) != len(set(student_ids)):
            raise serializers.ValidationError(
                "Duplicate student_id entries are not allowed in a single submission."
            )
        return entries


class ResultReleaseActionSerializer(serializers.Serializer):
    """Payload for publish / unpublish result actions."""

    class_id = serializers.UUIDField()
    term_id = serializers.UUIDField()


class ReportCardDownloadSerializer(serializers.Serializer):
    """Query parameters for the report card download endpoint."""

    student_id = serializers.UUIDField()
    term_id = serializers.UUIDField()
