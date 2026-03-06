from django.contrib import admin

from .models import Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        "registration_number",
        "first_name",
        "last_name",
        "school",
        "student_class",
        "gender",
        "status",
        "created_at",
    )
    list_filter = ("status", "gender", "school", "student_class")
    search_fields = ("first_name", "last_name", "registration_number")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("school", "last_name", "first_name")
