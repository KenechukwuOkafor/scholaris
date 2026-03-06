from django.contrib import admin

from .models import AssessmentType, ResultStatistics, Score, TeachingAssignment


@admin.register(AssessmentType)
class AssessmentTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "term", "weight", "order", "created_at")
    list_filter = ("school", "term")
    search_fields = ("name",)
    ordering = ("school", "term", "order", "name")
    readonly_fields = ("id", "max_score", "created_at", "updated_at")


@admin.register(TeachingAssignment)
class TeachingAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "teacher",
        "subject",
        "school_class",
        "school",
        "created_at",
    )
    list_filter = ("school", "school_class", "subject")
    search_fields = (
        "teacher__first_name",
        "teacher__last_name",
        "subject__name",
        "school_class__name",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("school", "school_class__name", "subject__name")


@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "subject",
        "term",
        "assessment_type",
        "score",
        "school",
        "created_at",
    )
    list_filter = ("school", "term", "subject", "assessment_type")
    search_fields = (
        "student__first_name",
        "student__last_name",
        "subject__name",
    )
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(ResultStatistics)
class ResultStatisticsAdmin(admin.ModelAdmin):
    list_display = (
        "school_class",
        "subject",
        "term",
        "highest_score",
        "lowest_score",
        "class_average",
        "school",
        "created_at",
    )
    list_filter = ("school", "term", "school_class")
    search_fields = ("school_class__name", "subject__name")
    readonly_fields = ("id", "created_at", "updated_at")
