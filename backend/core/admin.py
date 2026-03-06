from django.contrib import admin

from .models import School, SchoolClass, Session, Subject, Term


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "school_type", "email", "phone", "status", "created_at")
    list_filter = ("status", "school_type")
    search_fields = ("name", "email", "slug")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "start_date", "end_date", "is_active")
    list_filter = ("is_active", "school")
    search_fields = ("name", "school__name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ("name", "session", "school", "start_date", "end_date", "is_active")
    list_filter = ("is_active", "term_number", "school")
    search_fields = ("name", "session__name", "school__name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "order", "created_at")
    list_filter = ("school",)
    search_fields = ("name", "school__name")
    ordering = ("school", "order", "name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "school", "created_at")
    list_filter = ("school",)
    search_fields = ("name", "code", "school__name")
    readonly_fields = ("id", "created_at", "updated_at")
