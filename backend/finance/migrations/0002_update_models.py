"""
Finance migration 0002 — update models to match spec:

  • StudentInvoice.status   — max_length 10→15, choices → UNPAID/PARTIALLY_PAID/PAID
  • PaymentTransaction.payment_method — max_length 20→10, choices → cash/bank/pos/online
  • PaymentTransaction.transaction_reference — drop unique constraint, add blank=True
  • Receipt.transaction — OneToOneField → ForeignKey (allow multiple receipts per txn)
  • Receipt.pdf_file — null/blank → required FileField
  • Receipt — add idx_receipt_school_txn index
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0001_initial"),
    ]

    operations = [
        # ── StudentInvoice ────────────────────────────────────────────────
        migrations.AlterField(
            model_name="studentinvoice",
            name="status",
            field=models.CharField(
                choices=[
                    ("UNPAID", "Unpaid"),
                    ("PARTIALLY_PAID", "Partially Paid"),
                    ("PAID", "Paid"),
                ],
                db_index=True,
                default="UNPAID",
                max_length=15,
            ),
        ),
        # ── PaymentTransaction — choices & max_length ─────────────────────
        migrations.AlterField(
            model_name="paymenttransaction",
            name="payment_method",
            field=models.CharField(
                choices=[
                    ("cash", "Cash"),
                    ("bank", "Bank Transfer"),
                    ("pos", "POS"),
                    ("online", "Online"),
                ],
                db_index=True,
                default="cash",
                max_length=10,
            ),
        ),
        # ── PaymentTransaction — drop unique on transaction_reference ─────
        migrations.AlterField(
            model_name="paymenttransaction",
            name="transaction_reference",
            field=models.CharField(
                blank=True,
                help_text="Payment reference code. Auto-generated when blank.",
                max_length=100,
            ),
        ),
        # ── Receipt — OneToOneField → ForeignKey ──────────────────────────
        migrations.AlterField(
            model_name="receipt",
            name="transaction",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="receipts",
                to="finance.paymenttransaction",
            ),
        ),
        # ── Receipt — pdf_file: nullable → required ───────────────────────
        # No rows exist in Receipt table, so a one-off default of "" is safe.
        migrations.AlterField(
            model_name="receipt",
            name="pdf_file",
            field=models.FileField(upload_to="receipts/"),
        ),
        # ── Receipt — new index on (school, transaction) ──────────────────
        migrations.AddIndex(
            model_name="receipt",
            index=models.Index(
                fields=["school", "transaction"],
                name="idx_receipt_school_txn",
            ),
        ),
    ]
