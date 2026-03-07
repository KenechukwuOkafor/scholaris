"""
Bursar Dashboard Service.

Returns fee collection metrics across all terms, focused on financial health.
Reads from FinancialAnalytics + live invoice data for recent transactions.
Cached in Redis for 300 seconds.

Cache key: analytics:bursar_dashboard:{school_id}
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, Q, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

CACHE_TTL = 300


def get_bursar_dashboard(school) -> dict:
    """
    Return a financial metrics dict for the bursar.

    Args:
        school: a School instance.

    Returns:
        JSON-serialisable dict.
    """
    cache_key = f"analytics:bursar_dashboard:{school.pk}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = _build_bursar_dashboard(school)
    cache.set(cache_key, result, CACHE_TTL)
    return result


def _build_bursar_dashboard(school) -> dict:
    from analytics.models import FinancialAnalytics
    from core.models import Term
    from finance.models import PaymentTransaction, StudentInvoice

    today = timezone.localdate()

    # Active term.
    try:
        active_term = Term.objects.for_school(school).get(is_active=True)
    except Term.DoesNotExist:
        active_term = None

    # Per-term breakdown from analytics table (all terms).
    term_breakdown = []
    for fa in (
        FinancialAnalytics.objects
        .for_school(school)
        .select_related("term", "term__session")
        .order_by("-term__start_date")
    ):
        term_breakdown.append({
            "term":                  str(fa.term),
            "session":               fa.term.session.name,
            "total_invoiced":        str(fa.total_invoiced),
            "total_collected":       str(fa.total_collected),
            "total_outstanding":     str(fa.total_outstanding),
            "collection_rate":       str(fa.collection_rate),
            "fully_paid_count":      fa.fully_paid_count,
            "partially_paid_count":  fa.partially_paid_count,
            "unpaid_count":          fa.unpaid_count,
            "is_active_term":        (active_term is not None and fa.term_id == active_term.pk),
        })

    # School-wide all-time totals (single aggregation).
    all_time = (
        StudentInvoice.objects
        .for_school(school)
        .aggregate(
            total_invoiced=Sum("amount_due"),
            total_collected=Sum("amount_paid"),
            total_outstanding=Sum(
                "balance",
                filter=Q(status__in=[
                    StudentInvoice.Status.UNPAID,
                    StudentInvoice.Status.PARTIALLY_PAID,
                ]),
            ),
            paid_count=Count("id", filter=Q(status=StudentInvoice.Status.PAID)),
            partial_count=Count("id", filter=Q(status=StudentInvoice.Status.PARTIALLY_PAID)),
            unpaid_count=Count("id", filter=Q(status=StudentInvoice.Status.UNPAID)),
        )
    )
    invoiced   = all_time["total_invoiced"]  or Decimal("0.00")
    collected  = all_time["total_collected"] or Decimal("0.00")
    collection_rate = (
        round(collected / invoiced * 100, 2) if invoiced else Decimal("0.00")
    )

    # Recent transactions (last 10, live query for freshness).
    recent_txns = []
    for txn in (
        PaymentTransaction.objects
        .for_school(school)
        .select_related("student", "invoice__term")
        .order_by("-paid_at")[:10]
    ):
        recent_txns.append({
            "student":    str(txn.student),
            "amount":     str(txn.amount),
            "method":     txn.get_payment_method_display(),
            "reference":  txn.transaction_reference,
            "paid_at":    txn.paid_at.isoformat(),
            "term":       str(txn.invoice.term),
        })

    return {
        "school":      school.name,
        "currency":    school.currency,
        "as_of":       str(today),
        "all_time": {
            "total_invoiced":    str(invoiced),
            "total_collected":   str(collected),
            "total_outstanding": str(all_time["total_outstanding"] or Decimal("0.00")),
            "collection_rate":   str(collection_rate),
            "paid_count":        all_time["paid_count"] or 0,
            "partial_count":     all_time["partial_count"] or 0,
            "unpaid_count":      all_time["unpaid_count"] or 0,
        },
        "by_term":          term_breakdown,
        "recent_payments":  recent_txns,
    }


def invalidate_bursar_dashboard_cache(school) -> None:
    cache.delete(f"analytics:bursar_dashboard:{school.pk}")
