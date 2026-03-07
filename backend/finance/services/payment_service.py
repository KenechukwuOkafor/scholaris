"""
PaymentService — create invoices, record payments, and issue receipts.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from core.models import Term
from core.services.audit_service import ACTION_PAYMENT_RECORD, log_action
from enrollment.models import Student
from finance.models import (
    FeeStructure,
    PaymentTransaction,
    Receipt,
    StudentInvoice,
)


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------


def create_invoice(student: Student, term: Term) -> StudentInvoice:
    """
    Create a StudentInvoice for *student* in *term*.

    Looks up the FeeStructure for the student's class and term to determine
    amount_due.  The invoice is initialised with:
        - amount_paid = 0
        - balance     = fee_structure.total_amount
        - status      = UNPAID

    Args:
        student: the student to invoice.
        term:    the term the invoice covers.

    Returns:
        The newly created StudentInvoice.

    Raises:
        rest_framework.exceptions.ValidationError — student has no class, or
        an invoice for this student/term already exists.
        rest_framework.exceptions.NotFound — no FeeStructure for this class/term.
    """
    school_class = student.student_class
    if school_class is None:
        raise ValidationError(
            f"Student '{student}' is not assigned to a class. "
            "Assign a class before creating an invoice."
        )

    try:
        fee_structure = FeeStructure.objects.get(
            school=student.school,
            school_class=school_class,
            term=term,
        )
    except FeeStructure.DoesNotExist:
        raise NotFound(
            f"No fee structure found for '{school_class}' in '{term}'. "
            "Create a FeeStructure first."
        )

    try:
        invoice = StudentInvoice.objects.create(
            school=student.school,
            student=student,
            term=term,
            amount_due=fee_structure.total_amount,
        )
    except IntegrityError:
        raise ValidationError(
            f"An invoice for '{student}' in '{term}' already exists."
        )

    return invoice


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------


def record_payment(
    student: Student,
    amount: Decimal,
    payment_method: str,
    transaction_reference: str = "",
    actor=None,
) -> PaymentTransaction:
    """
    Record a payment against the student's most recent open invoice.

    Looks up the latest UNPAID or PARTIALLY_PAID invoice for *student*,
    then creates a PaymentTransaction and updates the invoice in one atomic
    block.

    Status transitions:
        amount_paid >= amount_due  → PAID
        amount_paid <  amount_due  → PARTIALLY_PAID

    Args:
        student:               the paying student.
        amount:                payment amount (must be > 0).
        payment_method:        one of PaymentTransaction.PaymentMethod choices
                               (cash / bank / pos / online).
        transaction_reference: optional reference string; auto-generated when
                               blank.

    Returns:
        The created PaymentTransaction.

    Raises:
        rest_framework.exceptions.NotFound — no open invoice exists.
        rest_framework.exceptions.ValidationError — amount ≤ 0.
    """
    if amount <= 0:
        raise ValidationError("Payment amount must be greater than zero.")

    # Find the latest open invoice (UNPAID or PARTIALLY_PAID).
    invoice = (
        StudentInvoice.objects
        .for_school(student.school)
        .filter(
            student=student,
            status__in=[
                StudentInvoice.Status.UNPAID,
                StudentInvoice.Status.PARTIALLY_PAID,
            ],
        )
        .order_by("-created_at")
        .first()
    )

    if invoice is None:
        raise NotFound(
            f"No open invoice found for '{student}'. "
            "Create an invoice first via create_invoice()."
        )

    ref = transaction_reference or f"TXN-{uuid.uuid4().hex[:12].upper()}"

    with transaction.atomic():
        txn = PaymentTransaction.objects.create(
            school=student.school,
            student=student,
            invoice=invoice,
            amount=amount,
            payment_method=payment_method,
            transaction_reference=ref,
        )

        invoice.amount_paid = (invoice.amount_paid or Decimal("0")) + amount

        if invoice.amount_paid >= invoice.amount_due:
            invoice.status = StudentInvoice.Status.PAID
        else:
            invoice.status = StudentInvoice.Status.PARTIALLY_PAID

        # balance is recomputed inside StudentInvoice.save()
        invoice.save(update_fields=["amount_paid", "balance", "status", "updated_at"])

    log_action(
        actor=actor,
        action=ACTION_PAYMENT_RECORD,
        target_model="PaymentTransaction",
        target_id=txn.id,
        metadata={
            "student": str(student),
            "amount": str(amount),
            "method": payment_method,
            "invoice_id": str(invoice.id),
            "invoice_status": invoice.status,
        },
        school=student.school,
    )

    return txn


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def generate_receipt(txn: PaymentTransaction) -> Receipt:
    """
    Generate a Receipt PDF for *txn* and persist it.

    A new receipt is created on every call (Receipt uses ForeignKey, so
    multiple receipts per transaction are valid — e.g. for reprints).

    The receipt number follows the format: RCP-<YEAR>-<8-hex-chars>.
    The PDF is stored under receipts/.

    Args:
        txn: a PaymentTransaction instance (must have .student and .invoice
             accessible without extra queries).

    Returns:
        The newly created Receipt instance.
    """
    year = timezone.now().year
    receipt_number = f"RCP-{year}-{uuid.uuid4().hex[:8].upper()}"

    pdf_bytes = _render_receipt_pdf(receipt_number, txn)

    receipt = Receipt.objects.create(
        school=txn.school,
        transaction=txn,
        receipt_number=receipt_number,
        pdf_file=ContentFile(pdf_bytes, name=f"{receipt_number}.pdf"),
    )

    return receipt


# ---------------------------------------------------------------------------
# PDF renderer
# ---------------------------------------------------------------------------


def _render_receipt_pdf(receipt_number: str, txn: PaymentTransaction) -> bytes:
    """Render a minimal HTML receipt to PDF bytes via WeasyPrint."""
    from weasyprint import HTML

    student = txn.student
    invoice = txn.invoice

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body   {{ font-family: sans-serif; margin: 40px; color: #111; }}
  h1     {{ font-size: 22px; margin-bottom: 4px; }}
  .sub   {{ color: #555; font-size: 13px; margin-bottom: 24px; }}
  table  {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
  td     {{ padding: 8px 12px; border-bottom: 1px solid #e0e0e0; }}
  .label {{ color: #555; width: 40%; }}
  .footer{{ margin-top: 40px; font-size: 11px; color: #999; }}
</style>
</head>
<body>
  <h1>{txn.school.name}</h1>
  <div class="sub">Official Payment Receipt</div>
  <table>
    <tr><td class="label">Receipt No.</td>
        <td><strong>{receipt_number}</strong></td></tr>
    <tr><td class="label">Date</td>
        <td>{txn.paid_at.strftime("%d %B %Y, %I:%M %p")}</td></tr>
    <tr><td class="label">Student</td>
        <td>{student.first_name} {student.last_name}</td></tr>
    <tr><td class="label">Reg. No.</td>
        <td>{student.registration_number}</td></tr>
    <tr><td class="label">Term</td>
        <td>{invoice.term}</td></tr>
    <tr><td class="label">Payment Method</td>
        <td>{txn.get_payment_method_display()}</td></tr>
    <tr><td class="label">Reference</td>
        <td>{txn.transaction_reference}</td></tr>
    <tr><td class="label">Amount Paid</td>
        <td>&#8358;{txn.amount:,.2f}</td></tr>
    <tr><td class="label">Outstanding Balance</td>
        <td>&#8358;{invoice.balance:,.2f}</td></tr>
    <tr><td class="label">Invoice Status</td>
        <td>{invoice.get_status_display()}</td></tr>
  </table>
  <div class="footer">
    This is a computer-generated receipt. No signature required.
  </div>
</body>
</html>"""

    return HTML(string=html).write_pdf()
