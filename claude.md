# Scholaris AI Development Rules

Scholaris is a multi-tenant SaaS platform for primary and secondary schools.

Tech Stack:
- Django 5+
- Django REST Framework
- PostgreSQL
- Redis
- Celery
- JWT Authentication
- S3-compatible storage
- Docker infrastructure

Architecture Rules:

1. Multi-Tenant System
Every tenant is a school.
All tenant data must reference a School model.

2. UUID Primary Keys
All models must use UUIDField as primary key.

3. Finance System
Finance uses a ledger-based accounting system.
All money values stored as integers (kobo).

4. Academic Results
Results are stored in gradebook models.
Approved results generate immutable JSON snapshots.

5. Security
No cross-school data access is allowed.
All queries must be scoped to school.

6. Docker Infrastructure
The system runs inside Docker containers.

Services:
- Django Web
- PostgreSQL
- Redis
- Celery Worker

7. Code Quality Rules
- Explicit related_name on all ForeignKeys
- Use model validation
- Add database indexes where needed
- Avoid business logic inside views

8. AI Development Rule
Claude should generate production-grade Django code only.
Avoid shortcuts or simplified implementations.