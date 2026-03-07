from django.contrib import admin

from django.db import models as db_models
from django.forms import Textarea

from .models import (
    AssessmentType,
    ReportCardFile,
    ReportCardTemplate,
    ResultRelease,
    ResultStatistics,
    Score,
    StudentTraitRating,
    TeachingAssignment,
    Trait,
    TraitCategory,
    TraitScale,
)


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


@admin.register(ReportCardTemplate)
class ReportCardTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "is_active", "created_at", "updated_at")
    list_filter = ("school", "is_active")
    search_fields = ("name", "school__name")
    ordering = ("school", "name")
    readonly_fields = ("id", "created_at", "updated_at")
    formfield_overrides = {
        db_models.TextField: {"widget": Textarea(attrs={"rows": 30, "cols": 120})},
    }


@admin.register(ReportCardFile)
class ReportCardFileAdmin(admin.ModelAdmin):
    list_display = ("student", "term", "pdf_file", "generated_at", "school")
    list_filter = ("school", "term")
    search_fields = ("student__first_name", "student__last_name", "student__registration_number")
    readonly_fields = ("id", "generated_at", "created_at", "updated_at")
    ordering = ("-generated_at",)


@admin.register(ResultRelease)
class ResultReleaseAdmin(admin.ModelAdmin):
    list_display = ("school_class", "term", "is_published", "published_at", "school", "updated_at")
    list_filter = ("school", "is_published", "term")
    search_fields = ("school_class__name", "term__name")
    ordering = ("school_class__name", "term__name")
    readonly_fields = ("id", "published_at", "created_at", "updated_at")


@admin.register(TraitCategory)
class TraitCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "display_order", "school", "created_at")
    list_filter = ("school",)
    search_fields = ("name",)
    ordering = ("school", "display_order", "name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Trait)
class TraitAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "display_order", "school", "created_at")
    list_filter = ("school", "category")
    search_fields = ("name", "category__name")
    ordering = ("school", "category__display_order", "display_order", "name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(TraitScale)
class TraitScaleAdmin(admin.ModelAdmin):
    list_display = ("label", "numeric_value", "display_order", "school", "created_at")
    list_filter = ("school",)
    search_fields = ("label",)
    ordering = ("school", "display_order", "-numeric_value")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(StudentTraitRating)
class StudentTraitRatingAdmin(admin.ModelAdmin):
    list_display = ("student", "term", "trait", "scale", "school", "created_at")
    list_filter = ("school", "term", "trait__category")
    search_fields = (
        "student__first_name",
        "student__last_name",
        "trait__name",
        "trait__category__name",
    )
    readonly_fields = ("id", "created_at", "updated_at")
