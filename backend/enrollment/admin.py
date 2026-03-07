from django.contrib import admin, messages

from core.models import SchoolClass, Session

from .models import (
    AttendanceRecord,
    AttendanceSession,
    Parent,
    Student,
    StudentEnrollment,
    StudentParent,
)


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


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ("school_class", "date", "marked_by", "school", "created_at")
    list_filter = ("school", "school_class", "date")
    search_fields = ("school_class__name", "marked_by__username")
    ordering = ("-date", "school_class__name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("student", "session", "status", "school", "created_at")
    list_filter = ("school", "status", "session__date")
    search_fields = ("student__first_name", "student__last_name", "student__registration_number")
    ordering = ("-session__date", "student__last_name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Parent)
class ParentAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "school", "created_at")
    list_filter = ("school",)
    search_fields = ("name", "phone", "email")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("school", "name")


@admin.register(StudentParent)
class StudentParentAdmin(admin.ModelAdmin):
    list_display = ("parent", "student", "relationship", "school", "created_at")
    list_filter = ("school", "relationship")
    search_fields = (
        "parent__name",
        "student__first_name",
        "student__last_name",
        "student__registration_number",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("student__last_name", "parent__name")


# ---------------------------------------------------------------------------
# StudentEnrollment admin
# ---------------------------------------------------------------------------


@admin.action(description="Promote Class — move selected students to the next class")
def promote_class_action(modeladmin, request, queryset):
    """
    Admin action on StudentEnrollment.

    For each selected enrollment the action:
      1. Finds the next SchoolClass for that school by ascending `order`.
      2. Uses the school's currently active Session as the target session.
      3. Calls promote_student() — idempotent, safe to re-run.

    Failures (no next class, no active session) are reported as individual
    error messages without aborting other promotions.
    """
    from .services.promotion_service import promote_student

    promoted = 0
    skipped = 0

    for enrollment in queryset.select_related(
        "student__school", "school_class"
    ):
        school = enrollment.school
        current_class = enrollment.school_class

        # Find the next class by order within the same school.
        next_class = (
            SchoolClass.objects.for_school(school)
            .filter(order__gt=current_class.order)
            .order_by("order")
            .first()
        )
        if next_class is None:
            modeladmin.message_user(
                request,
                f"'{current_class.name}' has no higher class to promote into "
                f"(student: {enrollment.student}).",
                messages.WARNING,
            )
            continue

        # Find the active session for this school.
        try:
            session = Session.objects.for_school(school).get(is_active=True)
        except Session.DoesNotExist:
            modeladmin.message_user(
                request,
                f"No active session found for school '{school.name}'. "
                f"Activate a session before promoting.",
                messages.ERROR,
            )
            continue

        try:
            _, created = promote_student(enrollment.student, next_class, session)
            if created:
                promoted += 1
            else:
                skipped += 1
        except Exception as exc:
            modeladmin.message_user(
                request,
                f"Failed to promote {enrollment.student}: {exc}",
                messages.ERROR,
            )

    if promoted:
        modeladmin.message_user(
            request,
            f"Successfully promoted {promoted} student(s).",
            messages.SUCCESS,
        )
    if skipped:
        modeladmin.message_user(
            request,
            f"Skipped {skipped} student(s) already enrolled for the active session.",
            messages.WARNING,
        )


@admin.register(StudentEnrollment)
class StudentEnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "school_class",
        "session",
        "is_current",
        "school",
        "created_at",
    )
    list_filter = ("school", "school_class", "session", "is_current")
    search_fields = (
        "student__first_name",
        "student__last_name",
        "student__registration_number",
        "school_class__name",
        "session__name",
    )
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-session__start_date", "school_class__name", "student__last_name")
    actions = [promote_class_action]
