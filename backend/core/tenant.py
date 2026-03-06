"""
Tenant resolution utilities.

get_request_school(request)
    Returns the School bound to the authenticated user.

    - Normal users: must have a UserProfile; raises PermissionDenied otherwise.
    - Staff / superusers: may operate without a profile (admin tools, management
      commands). Returns None so callers can fall back to payload-derived school.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied


def get_request_school(request):
    """
    Return the School for the authenticated user.

    Raises PermissionDenied for non-staff users who have no UserProfile.
    Returns None for staff users without a profile (admin fallback).
    """
    user = request.user

    try:
        return user.profile.school
    except Exception:
        pass

    if user.is_staff:
        return None

    raise PermissionDenied(
        "Your account is not linked to a school. "
        "Contact your administrator."
    )
