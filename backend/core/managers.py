"""
Tenant-aware ORM manager for all school-scoped models.

Usage
-----
Every model that inherits from SchoolScopedModel automatically gets
SchoolManager as its default manager, so:

    Student.objects.for_school(school)          # → filtered QuerySet
    Score.objects.for_school(school).filter(…)  # → chainable
"""

from django.db import models


class SchoolQuerySet(models.QuerySet):
    def for_school(self, school) -> "SchoolQuerySet":
        """Return only rows that belong to the given school."""
        return self.filter(school=school)


class SchoolManager(models.Manager):
    def get_queryset(self) -> SchoolQuerySet:
        return SchoolQuerySet(self.model, using=self._db)

    def for_school(self, school) -> SchoolQuerySet:
        """Convenience: School.objects.for_school(school) without .all()."""
        return self.get_queryset().for_school(school)
