from django.contrib import admin

from .models import Notification, WhatsAppMessage


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "type",
        "recipient_parent",
        "recipient_user",
        "is_read",
        "created_at",
    )
    list_filter = ("type", "is_read")
    search_fields = (
        "title",
        "message",
        "recipient_user__username",
        "recipient_parent__name",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-created_at",)


@admin.register(WhatsAppMessage)
class WhatsAppMessageAdmin(admin.ModelAdmin):
    list_display = (
        "phone",
        "student",
        "term",
        "status",
        "sent_at",
        "created_at",
    )
    list_filter = ("status", "term")
    search_fields = (
        "phone",
        "student__first_name",
        "student__last_name",
        "student__registration_number",
        "parent__name",
    )
    readonly_fields = ("id", "created_at", "updated_at", "sent_at")
    ordering = ("-created_at",)
