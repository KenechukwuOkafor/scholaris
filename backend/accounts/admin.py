from django.contrib import admin

from .models import Teacher, UserProfile


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = (
        "first_name",
        "last_name",
        "email",
        "phone",
        "school",
        "status",
        "created_at",
    )
    list_filter = ("status", "school")
    search_fields = ("first_name", "last_name", "email")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("school", "last_name", "first_name")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "school", "created_at")
    list_filter = ("school",)
    search_fields = ("user__username", "user__email", "school__name")
    readonly_fields = ("created_at", "updated_at")
