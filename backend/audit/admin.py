from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "timestamp",
        "action",
        "actor",
        "target_model",
        "target_id",
        "school",
    )
    list_filter = ("action", "actor", "timestamp", "school")
    search_fields = (
        "action",
        "target_model",
        "actor__username",
        "metadata",
    )
    readonly_fields = (
        "id",
        "school",
        "actor",
        "action",
        "target_model",
        "target_id",
        "metadata",
        "timestamp",
        "created_at",
        "updated_at",
    )
    ordering = ("-timestamp",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
