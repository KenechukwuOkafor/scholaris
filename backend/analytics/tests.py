"""
Analytics engine tests.

Run with:
    python manage.py test analytics --settings=scholaris.settings.dev -v 2

Covers:
- Analytics rows are created by Celery tasks.
- Cache keys are populated by service functions.
- Aggregated metrics are accurate against source data.
- Tenant isolation: School A cannot see School B's analytics rows.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone


# ---------------------------------------------------------------------------
# Helpers / Factories
# ---------------------------------------------------------------------------

def _make_school(name="Test School", slug=None):
    from core.models import School
    return School.objects.create(
        name=name,
        slug=slug or name.lower().replace(" ", "-"),
        school_type=School.SchoolType.SECONDARY,
        email=f"{(slug or name).replace(' ', '')}@test.com",
    )


def _make_session(school, name="2024/2025", active=True):
    from core.models import Session
    return Session.objects.create(
        school=school,
        name=name,
        start_date=date(2024, 9, 1),
        end_date=date(2025, 7, 31),
        is_active=active,
    )


def _make_term(school, session, number=1, active=True):
    from core.models import Term
    start = date(2024, 9, 1) if number == 1 else date(2025, 1, 7)
    end   = date(2024, 12, 20) if number == 1 else date(2025, 3, 28)
    return Term.objects.create(
        school=school,
        session=session,
        term_number=number,
        start_date=start,
        end_date=end,
        is_active=active,
    )


def _make_class(school, name="JSS 1"):
    from core.models import SchoolClass
    return SchoolClass.objects.create(school=school, name=name)


def _make_subject(school, name="Mathematics"):
    from core.models import Subject
    return Subject.objects.create(school=school, name=name)


def _make_student(school, klass, reg="S001", gender=None):
    from enrollment.models import Student
    return Student.objects.create(
        school=school,
        student_class=klass,
        registration_number=reg,
        first_name="Test",
        last_name="Student",
        gender=gender or Student.Gender.MALE,
        status=Student.Status.ACTIVE,
    )


def _make_teacher(school, email="teacher@school.com"):
    from accounts.models import Teacher
    return Teacher.objects.create(
        school=school,
        first_name="Test",
        last_name="Teacher",
        email=email,
        status=Teacher.Status.ACTIVE,
    )


def _make_invoice(school, student, term, amount_due=10000, amount_paid=0, status="UNPAID"):
    from finance.models import StudentInvoice
    return StudentInvoice.objects.create(
        school=school,
        student=student,
        term=term,
        amount_due=Decimal(str(amount_due)),
        amount_paid=Decimal(str(amount_paid)),
        status=status,
    )


def _make_result_summary(school, student, klass, term, total=300, average=60, position=1):
    from academics.models import ResultSummary
    return ResultSummary.objects.create(
        school=school,
        student=student,
        school_class=klass,
        term=term,
        total_score=Decimal(str(total)),
        average_score=Decimal(str(average)),
        position=position,
    )


def _make_student_subject_result(school, student, klass, subject, term, total=60):
    from academics.models import StudentSubjectResult
    return StudentSubjectResult.objects.create(
        school=school,
        student=student,
        school_class=klass,
        subject=subject,
        term=term,
        total_score=Decimal(str(total)),
    )


def _make_attendance_session(school, klass, att_date=None):
    from enrollment.models import AttendanceSession
    return AttendanceSession.objects.create(
        school=school,
        school_class=klass,
        date=att_date or timezone.localdate(),
    )


def _make_attendance_record(school, att_session, student, status="present"):
    from enrollment.models import AttendanceRecord
    return AttendanceRecord.objects.create(
        school=school,
        session=att_session,
        student=student,
        status=status,
    )


# ---------------------------------------------------------------------------
# Task Tests
# ---------------------------------------------------------------------------

class SchoolDailyMetricsTaskTest(TestCase):
    """update_school_daily_metrics creates/updates the correct row."""

    def setUp(self):
        cache.clear()
        self.school = _make_school("Alpha School", "alpha-school")
        self.session = _make_session(self.school)
        self.term = _make_term(self.school, self.session)
        self.klass = _make_class(self.school)
        self.student = _make_student(self.school, self.klass)
        self.teacher = _make_teacher(self.school)
        att_session = _make_attendance_session(self.school, self.klass)
        _make_attendance_record(self.school, att_session, self.student, "present")

    def test_row_created_with_correct_counts(self):
        from analytics.models import SchoolDailyMetrics
        from analytics.tasks import update_school_daily_metrics

        update_school_daily_metrics(str(self.school.pk))

        today = timezone.localdate()
        row = SchoolDailyMetrics.objects.for_school(self.school).get(date=today)

        self.assertEqual(row.active_students, 1)
        self.assertEqual(row.active_teachers, 1)
        self.assertEqual(row.present_count, 1)
        self.assertEqual(row.total_attendance_records, 1)
        self.assertEqual(row.attendance_rate, Decimal("100.00"))

    def test_idempotent_rerun(self):
        from analytics.models import SchoolDailyMetrics
        from analytics.tasks import update_school_daily_metrics

        update_school_daily_metrics(str(self.school.pk))
        update_school_daily_metrics(str(self.school.pk))

        count = SchoolDailyMetrics.objects.for_school(self.school).count()
        self.assertEqual(count, 1)

    def test_enrollment_analytics_created(self):
        from analytics.models import EnrollmentAnalytics
        from enrollment.models import StudentEnrollment
        from analytics.tasks import update_school_daily_metrics

        StudentEnrollment.objects.create(
            school=self.school,
            student=self.student,
            school_class=self.klass,
            session=self.session,
        )
        update_school_daily_metrics(str(self.school.pk))

        ea = EnrollmentAnalytics.objects.for_school(self.school).get(session=self.session)
        self.assertEqual(ea.total_enrolled, 1)
        self.assertEqual(ea.male_count, 1)


class FinancialMetricsTaskTest(TestCase):
    """update_financial_metrics aggregates invoices correctly."""

    def setUp(self):
        cache.clear()
        self.school = _make_school("Beta School", "beta-school")
        self.session = _make_session(self.school)
        self.term = _make_term(self.school, self.session)
        self.klass = _make_class(self.school)
        self.s1 = _make_student(self.school, self.klass, "S001")
        self.s2 = _make_student(self.school, self.klass, "S002")

    def test_financial_analytics_values(self):
        from analytics.models import FinancialAnalytics
        from analytics.tasks import update_financial_metrics

        _make_invoice(self.school, self.s1, self.term, 10000, 10000, "PAID")
        _make_invoice(self.school, self.s2, self.term, 10000, 5000, "PARTIALLY_PAID")

        update_financial_metrics(str(self.school.pk))

        fa = FinancialAnalytics.objects.for_school(self.school).get(term=self.term)
        self.assertEqual(fa.total_invoiced, Decimal("20000.00"))
        self.assertEqual(fa.total_collected, Decimal("15000.00"))
        self.assertEqual(fa.total_outstanding, Decimal("5000.00"))
        self.assertEqual(fa.collection_rate, Decimal("75.00"))
        self.assertEqual(fa.fully_paid_count, 1)
        self.assertEqual(fa.partially_paid_count, 1)
        self.assertEqual(fa.unpaid_count, 0)

    def test_zero_invoiced_no_division_error(self):
        from analytics.models import FinancialAnalytics
        from analytics.tasks import update_financial_metrics

        update_financial_metrics(str(self.school.pk))

        fa = FinancialAnalytics.objects.for_school(self.school).get(term=self.term)
        self.assertEqual(fa.collection_rate, Decimal("0.00"))


class ClassAnalyticsTaskTest(TestCase):
    """update_class_analytics aggregates ResultSummary correctly."""

    def setUp(self):
        cache.clear()
        self.school = _make_school("Gamma School", "gamma-school")
        self.session = _make_session(self.school)
        self.term = _make_term(self.school, self.session)
        self.klass = _make_class(self.school)
        self.subject = _make_subject(self.school)
        self.s1 = _make_student(self.school, self.klass, "S001")
        self.s2 = _make_student(self.school, self.klass, "S002")

    def test_class_analytics_values(self):
        from analytics.models import ClassAnalytics
        from analytics.tasks import update_class_analytics

        _make_result_summary(self.school, self.s1, self.klass, self.term, average=70)
        _make_result_summary(self.school, self.s2, self.klass, self.term, average=40, position=2)
        _make_student_subject_result(
            self.school, self.s1, self.klass, self.subject, self.term, 70
        )
        _make_student_subject_result(
            self.school, self.s2, self.klass, self.subject, self.term, 40
        )

        update_class_analytics(str(self.school.pk))

        ca = ClassAnalytics.objects.for_school(self.school).get(
            school_class=self.klass, term=self.term
        )
        self.assertEqual(ca.total_students, 2)
        self.assertEqual(ca.average_score, Decimal("55.00"))
        self.assertEqual(ca.highest_average, Decimal("70.00"))
        self.assertEqual(ca.lowest_average, Decimal("40.00"))
        self.assertEqual(ca.pass_rate, Decimal("50.00"))  # 1 of 2 >= 50
        self.assertEqual(ca.subjects_offered, 1)


class SubjectAnalyticsTaskTest(TestCase):
    """update_subject_analytics aggregates StudentSubjectResult correctly."""

    def setUp(self):
        cache.clear()
        self.school = _make_school("Delta School", "delta-school")
        self.session = _make_session(self.school)
        self.term = _make_term(self.school, self.session)
        self.klass = _make_class(self.school)
        self.subject = _make_subject(self.school)
        self.s1 = _make_student(self.school, self.klass, "S001")
        self.s2 = _make_student(self.school, self.klass, "S002")

    def test_subject_analytics_values(self):
        from analytics.models import SubjectAnalytics
        from analytics.tasks import update_subject_analytics

        _make_student_subject_result(
            self.school, self.s1, self.klass, self.subject, self.term, 80
        )
        _make_student_subject_result(
            self.school, self.s2, self.klass, self.subject, self.term, 40
        )

        update_subject_analytics(str(self.school.pk))

        sa = SubjectAnalytics.objects.for_school(self.school).get(
            subject=self.subject, school_class=self.klass, term=self.term
        )
        self.assertEqual(sa.total_students, 2)
        self.assertEqual(sa.average_score, Decimal("60.00"))
        self.assertEqual(sa.highest_score, Decimal("80.00"))
        self.assertEqual(sa.lowest_score, Decimal("40.00"))
        self.assertEqual(sa.pass_rate, Decimal("50.00"))


class AttendanceAnalyticsTaskTest(TestCase):
    """update_attendance_analytics aggregates records by class+term correctly."""

    def setUp(self):
        cache.clear()
        self.school = _make_school("Epsilon School", "epsilon-school")
        self.session = _make_session(self.school)
        self.term = _make_term(self.school, self.session)
        self.klass = _make_class(self.school)
        self.s1 = _make_student(self.school, self.klass, "S001")
        self.s2 = _make_student(self.school, self.klass, "S002")

    def test_attendance_analytics_values(self):
        from analytics.models import AttendanceAnalytics
        from analytics.tasks import update_attendance_analytics

        att_date = self.term.start_date + timedelta(days=1)
        att_session = _make_attendance_session(self.school, self.klass, att_date)
        _make_attendance_record(self.school, att_session, self.s1, "present")
        _make_attendance_record(self.school, att_session, self.s2, "absent")

        update_attendance_analytics(str(self.school.pk))

        aa = AttendanceAnalytics.objects.for_school(self.school).get(
            school_class=self.klass, term=self.term
        )
        self.assertEqual(aa.total_sessions, 1)
        self.assertEqual(aa.total_records, 2)
        self.assertEqual(aa.present_count, 1)
        self.assertEqual(aa.absent_count, 1)
        self.assertEqual(aa.late_count, 0)
        self.assertEqual(aa.average_attendance_rate, Decimal("50.00"))


# ---------------------------------------------------------------------------
# Tenant Isolation Tests
# ---------------------------------------------------------------------------

class TenantIsolationTest(TestCase):
    """Analytics rows from School A must not be visible when querying School B."""

    def setUp(self):
        cache.clear()
        self.school_a = _make_school("School A", "school-a")
        self.school_b = _make_school("School B", "school-b")

        for school in (self.school_a, self.school_b):
            sess = _make_session(school, active=True)
            term = _make_term(school, sess)
            klass = _make_class(school)
            s = _make_student(school, klass)
            _make_invoice(school, s, term, 5000, 5000, "PAID")
            _make_result_summary(school, s, klass, term, average=75)

        from analytics.tasks import (
            update_class_analytics,
            update_financial_metrics,
            update_school_daily_metrics,
        )
        for school in (self.school_a, self.school_b):
            sid = str(school.pk)
            update_school_daily_metrics(sid)
            update_financial_metrics(sid)
            update_class_analytics(sid)

    def test_daily_metrics_isolation(self):
        from analytics.models import SchoolDailyMetrics

        a_rows = SchoolDailyMetrics.objects.for_school(self.school_a)
        b_rows = SchoolDailyMetrics.objects.for_school(self.school_b)
        self.assertFalse(a_rows.filter(school=self.school_b).exists())
        self.assertFalse(b_rows.filter(school=self.school_a).exists())

    def test_financial_analytics_isolation(self):
        from analytics.models import FinancialAnalytics

        a_rows = FinancialAnalytics.objects.for_school(self.school_a)
        b_rows = FinancialAnalytics.objects.for_school(self.school_b)
        self.assertFalse(a_rows.filter(school=self.school_b).exists())
        self.assertFalse(b_rows.filter(school=self.school_a).exists())

    def test_class_analytics_isolation(self):
        from analytics.models import ClassAnalytics

        a_rows = ClassAnalytics.objects.for_school(self.school_a)
        b_rows = ClassAnalytics.objects.for_school(self.school_b)
        self.assertFalse(a_rows.filter(school=self.school_b).exists())
        self.assertFalse(b_rows.filter(school=self.school_a).exists())


# ---------------------------------------------------------------------------
# Cache Tests
# ---------------------------------------------------------------------------

class CacheTest(TestCase):
    """Service functions populate Redis cache and return cached data on repeat calls."""

    def setUp(self):
        cache.clear()
        self.school = _make_school("Cache School", "cache-school")
        self.session = _make_session(self.school)
        self.term = _make_term(self.school, self.session)

    def test_admin_dashboard_cache_populated(self):
        from analytics.services.admin_dashboard_service import get_admin_dashboard

        cache_key = f"analytics:admin_dashboard:{self.school.pk}"
        self.assertIsNone(cache.get(cache_key))

        result = get_admin_dashboard(self.school)

        self.assertIsNotNone(cache.get(cache_key))
        self.assertEqual(result["school"], self.school.name)

    def test_admin_dashboard_returns_cached(self):
        from analytics.services.admin_dashboard_service import get_admin_dashboard

        first  = get_admin_dashboard(self.school)
        second = get_admin_dashboard(self.school)
        self.assertEqual(first, second)

    def test_bursar_dashboard_cache_populated(self):
        from analytics.services.bursar_dashboard_service import get_bursar_dashboard

        cache_key = f"analytics:bursar_dashboard:{self.school.pk}"
        get_bursar_dashboard(self.school)
        self.assertIsNotNone(cache.get(cache_key))

    def test_proprietor_dashboard_cache_populated(self):
        from analytics.services.proprietor_dashboard_service import get_proprietor_dashboard

        cache_key = f"analytics:proprietor_dashboard:{self.school.pk}"
        get_proprietor_dashboard(self.school)
        self.assertIsNotNone(cache.get(cache_key))

    def test_teacher_dashboard_cache_populated(self):
        from analytics.services.teacher_dashboard_service import get_teacher_dashboard

        teacher = _make_teacher(self.school)
        cache_key = f"analytics:teacher_dashboard:{self.school.pk}:{teacher.pk}"
        get_teacher_dashboard(self.school, teacher)
        self.assertIsNotNone(cache.get(cache_key))

    def test_invalidate_clears_admin_cache(self):
        from analytics.services.admin_dashboard_service import (
            get_admin_dashboard,
            invalidate_admin_dashboard_cache,
        )

        get_admin_dashboard(self.school)
        cache_key = f"analytics:admin_dashboard:{self.school.pk}"
        self.assertIsNotNone(cache.get(cache_key))

        invalidate_admin_dashboard_cache(self.school)
        self.assertIsNone(cache.get(cache_key))
