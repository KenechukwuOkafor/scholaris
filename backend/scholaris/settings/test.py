from .dev import *  # noqa: F401, F403

# Use the pre-existing 'scholaris' database (owned by the 'scholaris' pg role)
# as the test database so that no CREATEDB privilege is required.
DATABASES["default"]["TEST"] = {"NAME": "scholaris"}  # noqa: F405
