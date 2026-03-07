from decimal import Decimal

from django.db import models

from core.models import SchoolClass, SchoolScopedModel, Term
from enrollment.models import Student


class FeeStructure(SchoolScopedModel):
    """
    Defines the fee breakdown for a class in a term.

    total_amount is auto-computed from the four components in save().
    One row per (school_class, term).

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.PROTECT,
        related_name="fee_structures",
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name="fee_structures",
    )
    tuition_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    development_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    sports_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    exam_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        editable=False,
        help_text="Auto-computed: sum of all fee components.",
    )

    class Meta:
        db_table = "finance_feestructure"
        ordering = ["school_class__name", "term__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school_class", "term"],
                name="uniq_feestructure_class_term",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "term"],
                name="idx_feestructure_school_term",
            ),
            models.Index(
                fields=["school", "school_class", "term"],
                name="idx_feestructure_cls_term",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.school_class} — {self.term} (₦{self.total_amount:,.2f})"

    def save(self, *args, **kwargs) -> None:
        self.total_amount = (
            (self.tuition_fee or Decimal("0"))
            + (self.development_fee or Decimal("0"))
            + (self.sports_fee or Decimal("0"))
            + (self.exam_fee or Decimal("0"))
        )
        super().save(*args, **kwargs)


class StudentInvoice(SchoolScopedModel):
    """
    An end-of-term fee invoice for a student.

    One invoice per (student, term).  Status transitions:
        UNPAID → PARTIALLY_PAID → PAID

    balance is kept in sync with amount_due − amount_paid via save().

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    class Status(models.TextChoices):
        UNPAID         = "UNPAID",         "Unpaid"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
        PAID           = "PAID",           "Paid"

    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        editable=False,
        help_text="Auto-computed: amount_due − amount_paid.",
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.UNPAID,
        db_index=True,
    )

    class Meta:
        db_table = "finance_studentinvoice"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "term"],
                name="uniq_invoice_student_term",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "student"],
                name="idx_invoice_school_student",
            ),
            models.Index(
                fields=["school", "term", "status"],
                name="idx_invoice_school_term_status",
            ),
            # Compound index for record_payment()'s open-invoice lookup:
            #   .filter(student=student, status__in=[UNPAID, PARTIALLY_PAID])
            # Adding status to school+student eliminates the post-index status
            # filter on every payment write — the most frequent finance query.
            models.Index(
                fields=["school", "student", "status"],
                name="idx_invoice_student_status",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Invoice [{self.get_status_display()}] "
            f"{self.student} — {self.term} (balance: ₦{self.balance:,.2f})"
        )

    def save(self, *args, **kwargs) -> None:
        self.balance = (
            (self.amount_due or Decimal("0"))
            - (self.amount_paid or Decimal("0"))
        )
        super().save(*args, **kwargs)


class PaymentTransaction(SchoolScopedModel):
    """
    Records a single payment made against a StudentInvoice.

    Multiple transactions may exist per invoice (instalment payments).
    transaction_reference is an optional free-text field; auto-generated
    when blank.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    class PaymentMethod(models.TextChoices):
        CASH   = "cash",   "Cash"
        BANK   = "bank",   "Bank Transfer"
        POS    = "pos",    "POS"
        ONLINE = "online", "Online"

    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name="payment_transactions",
    )
    invoice = models.ForeignKey(
        StudentInvoice,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
        db_index=True,
    )
    transaction_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Payment reference code. Auto-generated when blank.",
    )
    paid_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "finance_paymenttransaction"
        ordering = ["-paid_at"]
        indexes = [
            models.Index(
                fields=["school", "student"],
                name="idx_payment_school_student",
            ),
            models.Index(
                fields=["school", "invoice"],
                name="idx_payment_school_invoice",
            ),
            # Compound index for time-ordered payment history per student:
            #   .filter(school=school, student=student).order_by("-created_at")
            # created_at as the third column lets PostgreSQL satisfy the ORDER BY
            # with an index scan rather than a sort step.
            models.Index(
                fields=["school", "student", "created_at"],
                name="idx_payment_student_created",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Payment ₦{self.amount:,.2f} [{self.get_payment_method_display()}] "
            f"— {self.student} (ref: {self.transaction_reference})"
        )


class Receipt(SchoolScopedModel):
    """
    A receipt issued for a PaymentTransaction.

    Uses ForeignKey (not OneToOneField) so that receipts can be regenerated
    without replacing the original.  receipt_number is globally unique.

    Inherits from SchoolScopedModel:
    - id         → UUIDField primary key
    - school     → ForeignKey(School, on_delete=PROTECT)
    - created_at → DateTimeField
    - updated_at → DateTimeField
    """

    transaction = models.ForeignKey(
        PaymentTransaction,
        on_delete=models.PROTECT,
        related_name="receipts",
    )
    receipt_number = models.CharField(max_length=50, unique=True)
    pdf_file = models.FileField(upload_to="receipts/")
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_receipt"
        ordering = ["-generated_at"]
        indexes = [
            models.Index(
                fields=["school", "receipt_number"],
                name="idx_receipt_school_number",
            ),
            models.Index(
                fields=["school", "transaction"],
                name="idx_receipt_school_txn",
            ),
        ]

    def __str__(self) -> str:
        return f"Receipt #{self.receipt_number} — {self.transaction}"
