from django.contrib import admin

from .models import (
    AttendanceAnalytics,
    ClassAnalytics,
    EnrollmentAnalytics,
    FinancialAnalytics,
    SchoolDailyMetrics,
    SubjectAnalytics,
)


@admin.register(SchoolDailyMetrics)
class SchoolDailyMetricsAdmin(admin.ModelAdmin):
    list_display = (
        "school",
        "date",
        "active_students",
        "active_teachers",
        "attendance_rate",
        "present_count",
        "total_attendance_records",
    )
    list_filter = ("school", "date")
    search_fields = ("school__name",)
    ordering = ("-date",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "date"


@admin.register(ClassAnalytics)
class ClassAnalyticsAdmin(admin.ModelAdmin):
    list_display = (
        "school_class",
        "term",
        "total_students",
        "average_score",
        "pass_rate",
        "highest_average",
        "lowest_average",
        "subjects_offered",
    )
    list_filter = ("school", "term", "school_class")
    search_fields = ("school__name", "school_class__name")
    ordering = ("-term__start_date", "school_class__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SubjectAnalytics)
class SubjectAnalyticsAdmin(admin.ModelAdmin):
    list_display = (
        "subject",
        "school_class",
        "term",
        "total_students",
        "average_score",
        "pass_rate",
        "highest_score",
        "lowest_score",
    )
    list_filter = ("school", "term", "school_class", "subject")
    search_fields = ("school__name", "subject__name", "school_class__name")
    ordering = ("-term__start_date", "subject__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(FinancialAnalytics)
class FinancialAnalyticsAdmin(admin.ModelAdmin):
    list_display = (
        "school",
        "term",
        "total_invoiced",
        "total_collected",
        "total_outstanding",
        "collection_rate",
        "fully_paid_count",
        "partially_paid_count",
        "unpaid_count",
    )
    list_filter = ("school", "term")
    search_fields = ("school__name",)
    ordering = ("-term__start_date",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(EnrollmentAnalytics)
class EnrollmentAnalyticsAdmin(admin.ModelAdmin):
    list_display = (
        "school",
        "session",
        "total_enrolled",
        "male_count",
        "female_count",
        "class_count",
    )
    list_filter = ("school", "session")
    search_fields = ("school__name",)
    ordering = ("-session__start_date",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(AttendanceAnalytics)
class AttendanceAnalyticsAdmin(admin.ModelAdmin):
    list_display = (
        "school_class",
        "term",
        "total_sessions",
        "total_records",
        "present_count",
        "absent_count",
        "late_count",
        "average_attendance_rate",
    )
    list_filter = ("school", "term", "school_class")
    search_fields = ("school__name", "school_class__name")
    ordering = ("-term__start_date", "school_class__name")
    readonly_fields = ("created_at", "updated_at")
