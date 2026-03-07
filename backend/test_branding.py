"""
Branding test: seed sample images, generate single report card PDF,
confirm images render correctly (present as data URIs in HTML, appear in PDF).

Run with:
    python test_branding.py
"""

import os
import sys
import struct
import zlib
import datetime
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scholaris.settings.dev")
django.setup()

from django.conf import settings
from django.core.files.base import ContentFile

from core.models import School, SchoolClass, Session, Term
from enrollment.models import Student
from academics.models import (
    AssessmentType, Score, ResultSummary, ResultStatistics, StudentSubjectResult
)
from academics.services.result_processor import ResultProcessor
from academics.services.reportcard_service import generate_report_card, _image_to_data_uri
from academics.services.reportcard_pdf_service import generate_report_card_pdf

results = []

def check(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print(f"  [{'✓' if passed else '✗'}] {name}" + (f"  ({detail})" if detail else ""))


# ---------------------------------------------------------------------------
# Minimal valid PNG builder (1×1 pixel, given RGB colour)
# ---------------------------------------------------------------------------

def _make_png(r=0, g=0, b=0) -> bytes:
    """Build a minimal 1×1 RGB PNG in memory — no Pillow required."""
    def chunk(name: bytes, data: bytes) -> bytes:
        c = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1×1, 8-bit, RGB
    raw  = b"\x00" + bytes([r, g, b])                      # filter byte + pixel
    idat = zlib.compress(raw)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# Fetch the Alpha school seeded in the e2e test
# ---------------------------------------------------------------------------

print("\n=== Setup ===")

try:
    school = School.objects.get(slug="alpha-school")
    check("Alpha School found", True)
except School.DoesNotExist:
    print("  [✗] Alpha School not found — run test_report_card_e2e.py first")
    sys.exit(1)

# Ensure media dirs exist
for subdir in ("schools/logos", "schools/signatures", "schools/stamps"):
    os.makedirs(settings.MEDIA_ROOT / subdir, exist_ok=True)

# ---------------------------------------------------------------------------
# Seed sample images onto the school
# ---------------------------------------------------------------------------

print("\n=== Seeding sample images ===")

school.logo.save("alpha_logo.png",       ContentFile(_make_png(70, 130, 180)),  save=False)
school.principal_signature.save(
    "alpha_signature.png", ContentFile(_make_png(30, 30, 30)),  save=False)
school.school_stamp.save(
    "alpha_stamp.png",     ContentFile(_make_png(200, 50, 50)), save=False)
school.save()

check("logo saved",               bool(school.logo.name))
check("principal_signature saved", bool(school.principal_signature.name))
check("school_stamp saved",        bool(school.school_stamp.name))
check("logo file exists on disk",
      os.path.isfile(school.logo.path))
check("signature file exists on disk",
      os.path.isfile(school.principal_signature.path))
check("stamp file exists on disk",
      os.path.isfile(school.school_stamp.path))

# ---------------------------------------------------------------------------
# Set next_term_begins on the term
# ---------------------------------------------------------------------------

term = Term.objects.filter(school=school).first()
term.next_term_begins = datetime.date(2026, 1, 12)
term.save()
check("next_term_begins saved", term.next_term_begins is not None)

# ---------------------------------------------------------------------------
# _image_to_data_uri helper
# ---------------------------------------------------------------------------

print("\n=== _image_to_data_uri helper ===")

logo_uri = _image_to_data_uri(school.logo)
check("logo data URI returned",        logo_uri is not None)
check("logo URI starts with data:",    logo_uri is not None and logo_uri.startswith("data:"))
check("logo URI is PNG",               logo_uri is not None and "image/png" in logo_uri)

sig_uri = _image_to_data_uri(school.principal_signature)
check("signature data URI returned",   sig_uri is not None)

stamp_uri = _image_to_data_uri(school.school_stamp)
check("stamp data URI returned",       stamp_uri is not None)

# None for empty field
school_reload = School.objects.get(pk=school.pk)
check("None for missing image",        _image_to_data_uri(None) is None)

# ---------------------------------------------------------------------------
# generate_report_card — school block present
# ---------------------------------------------------------------------------

print("\n=== generate_report_card school block ===")

# Fetch a student who actually has computed results for this term
summary_row = ResultSummary.objects.filter(school=school, term=term).select_related("student").first()
if not summary_row:
    print("  [✗] No ResultSummary found — run test_report_card_e2e.py first")
    sys.exit(1)
student = summary_row.student
report = generate_report_card(student, term)

check("school block present",               "school" in report)
check("school.name correct",                report["school"]["name"] == school.name)
check("school.logo is data URI",
      report["school"]["logo"] is not None and
      report["school"]["logo"].startswith("data:"))
check("school.principal_signature is data URI",
      report["school"]["principal_signature"] is not None and
      report["school"]["principal_signature"].startswith("data:"))
check("school.school_stamp is data URI",
      report["school"]["school_stamp"] is not None and
      report["school"]["school_stamp"].startswith("data:"))
check("next_term_begins in student_info",
      report["student_info"]["next_term_begins"] == "12 January, 2026")

# ---------------------------------------------------------------------------
# HTML template rendering — confirm images injected
# ---------------------------------------------------------------------------

print("\n=== Template rendering ===")

from django.template.loader import render_to_string

html = render_to_string("reportcards/report_card.html", {"report": report})

check("HTML non-empty",                    len(html) > 500)
check("school name in HTML",               school.name in html)
check("logo data URI in HTML",             "data:image/png" in html)
check("signature img tag present",         'class="signature"' in html)
check("stamp img tag present",             'class="stamp"' in html)
check("next_term_begins in HTML",          "12 January, 2026" in html)
check("student name in HTML",             report["student_info"]["name"] in html)
check("grade-badge in HTML",               "grade-badge" in html)
check("Principal's Signature label",       "Principal" in html)
check("School Stamp label",                "School Stamp" in html)

# ---------------------------------------------------------------------------
# PDF generation — confirm images survive WeasyPrint rendering
# ---------------------------------------------------------------------------

print("\n=== PDF generation with branding ===")

pdf = generate_report_card_pdf(student, term)

check("PDF bytes returned",                isinstance(pdf, bytes))
check("PDF magic header correct",          pdf[:4] == b"%PDF")
check("PDF substantially larger with images",
      len(pdf) > 5_000,
      f"{len(pdf):,} bytes")

# Save for visual inspection
out_path = settings.BASE_DIR / "test_branded_report.pdf"
with open(out_path, "wb") as f:
    f.write(pdf)
check("PDF written to disk",               os.path.isfile(out_path),
      str(out_path))

# ---------------------------------------------------------------------------
# Final table
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print(f"{'Check':<52} Result")
print("-" * 60)
for name, status, *detail in results:
    d = f"  ({detail[0]})" if detail else ""
    print(f"  {'✓' if status == 'PASS' else '✗'} {name:<50} {status}{d}")

passed = sum(1 for _, s, *_ in results if s == "PASS")
failed = sum(1 for _, s, *_ in results if s == "FAIL")
print("-" * 60)
print(f"  Total: {passed} passed, {failed} failed")
print("=" * 60)

if failed:
    sys.exit(1)
