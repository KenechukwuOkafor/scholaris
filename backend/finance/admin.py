from django.contrib import admin

from .models import FeeStructure, PaymentTransaction, Receipt, StudentInvoice


@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = (
        "school_class",
        "term",
        "tuition_fee",
        "development_fee",
        "sports_fee",
        "exam_fee",
        "total_amount",
        "school",
    )
    list_filter = ("school", "term")
    search_fields = ("school_class__name", "term__name")
    readonly_fields = ("id", "total_amount", "created_at", "updated_at")
    ordering = ("school_class__name", "term__name")


@admin.register(StudentInvoice)
class StudentInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "term",
        "amount_due",
        "amount_paid",
        "balance",
        "status",
        "school",
        "created_at",
    )
    list_filter = ("school", "status", "term")
    search_fields = (
        "student__first_name",
        "student__last_name",
        "student__registration_number",
    )
    readonly_fields = ("id", "balance", "created_at", "updated_at")
    ordering = ("-created_at",)


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "invoice",
        "amount",
        "payment_method",
        "transaction_reference",
        "paid_at",
        "school",
    )
    list_filter = ("school", "payment_method", "paid_at")
    search_fields = (
        "student__first_name",
        "student__last_name",
        "transaction_reference",
    )
    readonly_fields = ("id", "paid_at", "created_at", "updated_at")
    ordering = ("-paid_at",)


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "receipt_number",
        "transaction",
        "pdf_file",
        "generated_at",
        "school",
    )
    list_filter = ("school",)
    search_fields = (
        "receipt_number",
        "transaction__transaction_reference",
        "transaction__student__first_name",
        "transaction__student__last_name",
    )
    readonly_fields = ("id", "generated_at", "created_at", "updated_at")
    ordering = ("-generated_at",)
