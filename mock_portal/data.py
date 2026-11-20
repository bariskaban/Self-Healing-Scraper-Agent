"""The mock portal's tenders and files: made up, and the same on every run.

Nothing here reads a clock or a random number, so two portals built with the same arguments
hold the same tenders, the same file bytes and the same hashes.

Two rules the texts keep to, because the fetch layer reads signs off a page:
- no title holds a maintenance word ("maintenance", "onderhoud"): a tender's title is the
  `<h1>` of its page, and a maintenance word in a heading reads as a maintenance notice;
- every text is plain ASCII without markup characters, so it prints the same in HTML and in a PDF.
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TIMEZONE = "Europe/Amsterdam"
ZONE = ZoneInfo(TIMEZONE)

STATUS_OPEN = "Open"
STATUS_CANCELLED = "Cancelled"
# The portal's words and what each means in the output contract. The recipe uses the same maps.
STATUS_WORDS = {STATUS_OPEN: "open", "Closed": "closed", STATUS_CANCELLED: "withdrawn"}
PROCEDURE_WORDS = {"Open procedure": "open", "Restricted procedure": "restricted",
                   "Negotiated procedure": "negotiated", "Competitive dialogue": "other"}
NATURE_WORDS = {"Works": "works", "Services": "services", "Supplies": "supplies"}
COUNTRY = "Netherlands"
COUNTRY_CODE = "NL"

# How the portal prints a moment, and the same moment in the `datetime` attribute of `<time>`.
DATE_FORMAT = "%d.%m.%Y"
DATETIME_FORMAT = "%d.%m.%Y %H:%M"
MACHINE_FORMAT = "%Y-%m-%dT%H:%M"

# (name, short code, postal code, city)
_BUYERS = [
    ("Municipality of Amsterdam", "AMS", "1011 PN", "Amsterdam"),
    ("Municipality of Rotterdam", "RTM", "3011 AD", "Rotterdam"),
    ("Province of Utrecht", "PUT", "3584 BA", "Utrecht"),
    ("Eindhoven Regional Water Board", "ERW", "5611 EM", "Eindhoven"),
    ("Groningen University Hospital", "GUH", "9713 GZ", "Groningen"),
    ("Maastricht Public Transport Authority", "MPT", "6211 CL", "Maastricht"),
]

# (subject, contract nature word, CPV codes with their check digits). Codes of CPV 2008.
_SUBJECTS = [
    ("Renovation of the town hall roof", "Works", ["45000000-7", "45210000-2"]),
    ("Development of a permit application system", "Services", ["72000000-5", "72200000-7"]),
    ("Supply of office furniture", "Supplies", ["39000000-2", "39100000-3"]),
    ("Cleaning of public buildings", "Services", ["90000000-7", "90910000-9"]),
    ("Resurfacing of the ring road", "Works", ["45233120-6"]),
    ("Supply of electric service vehicles", "Supplies", ["34000000-7", "34100000-8"]),
    ("Engineering design for a cycle bridge", "Services", ["71000000-8", "71300000-1"]),
    ("Supply of laptops and monitors", "Supplies", ["30000000-9", "30200000-1"]),
    ("Security services for municipal sites", "Services", ["79000000-4", "79710000-4"]),
    ("Collection of household waste", "Services", ["90500000-2"]),
    ("Supply of medical imaging equipment", "Supplies", ["33000000-0", "33100000-1"]),
    ("Catering for staff restaurants", "Services", ["55000000-0", "55500000-5"]),
    ("Training courses for field staff", "Services", ["80000000-4", "80500000-9"]),
]
_PROCEDURES = ["Open procedure", "Open procedure", "Restricted procedure", "Open procedure",
               "Negotiated procedure", "Competitive dialogue"]
# Clock times that exist on every day of the year in Europe/Amsterdam (the switch to summer
# time skips 02:00 to 03:00 only).
_DEADLINE_TIMES = [(10, 0), (12, 0), (14, 0), (16, 0), (17, 0)]

_FIRST_PUBLICATION = date(2026, 1, 5)
_PUBLICATION_SPAN_DAYS = 280   # every publication date stays inside 2026
_FIRST_DEADLINE = date(2027, 1, 11)
_DEADLINE_SPAN_DAYS = 340      # every deadline stays inside 2027
# One fixed moment for the entries of every ZIP, so the archive's bytes never change.
_ZIP_ENTRY_TIME = (2026, 1, 5, 9, 0, 0)


@dataclass(frozen=True)
class File:
    """One document of a tender, as the portal serves it."""

    name: str
    content_type: str
    body: bytes

    @property
    def size(self) -> int:
        return len(self.body)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


@dataclass(frozen=True)
class Tender:
    """One tender, with the words the portal prints for it."""

    id: str
    number: int                # 1 is the oldest
    title: str
    buyer_name: str
    publication_date: date
    submission_deadline: datetime   # aware, Europe/Amsterdam
    reference_number: str
    description: str
    procedure_word: str
    nature_word: str
    cpv: tuple[str, ...]       # as printed, check digit included: "45000000-7"
    postal_code: str
    city: str
    files: tuple[File, ...]

    def file(self, name: str) -> File | None:
        return next((f for f in self.files if f.name == name), None)


def tender_id(number: int) -> str:
    """The portal's own identifier of tender `number` (1 is the oldest): MP-2026-0001."""
    return f"MP-2026-{number:04d}"


def print_date(day: date) -> str:
    return day.strftime(DATE_FORMAT)


def print_moment(moment: datetime) -> str:
    return moment.strftime(DATETIME_FORMAT)


def make_tenders(count: int) -> list[Tender]:
    """`count` tenders, oldest first. Tender `n` is the same whatever follows it, except its
    publication date, which is spread over 2026 by `count` so that a later tender is never older."""
    return [_make_tender(number, count) for number in range(1, count + 1)]


def _make_tender(number: int, count: int) -> Tender:
    buyer_name, buyer_code, postal_code, city = _BUYERS[number % len(_BUYERS)]
    subject, nature_word, cpv = _SUBJECTS[number % len(_SUBJECTS)]
    ident = tender_id(number)
    title = f"{subject}, {city} (lot {number})"
    published = _FIRST_PUBLICATION + timedelta(days=(number - 1) * _PUBLICATION_SPAN_DAYS // count)
    hour, minute = _DEADLINE_TIMES[number % len(_DEADLINE_TIMES)]
    closing_day = _FIRST_DEADLINE + timedelta(days=(number * 37) % _DEADLINE_SPAN_DAYS)
    deadline = datetime(closing_day.year, closing_day.month, closing_day.day, hour, minute, tzinfo=ZONE)
    reference = f"{buyer_code}.2026.{100 + number * 3:04d}"
    description = (f"{buyer_name} invites tenders for {subject.lower()} in {city}. "
                   f"The contract is lot {number} of the buyer's 2026 programme and runs for "
                   f"{12 + (number % 4) * 12} months. Tenders are sent in through this portal before the "
                   f"deadline; questions are answered in writing.")
    return Tender(
        id=ident, number=number, title=title, buyer_name=buyer_name, publication_date=published,
        submission_deadline=deadline, reference_number=reference, description=description,
        procedure_word=_PROCEDURES[number % len(_PROCEDURES)], nature_word=nature_word, cpv=tuple(cpv),
        postal_code=postal_code, city=city, files=tuple(_make_files(number, ident, title, reference)))


def _make_files(number: int, ident: str, title: str, reference: str) -> list[File]:
    """Two PDFs, a third for every even tender, and for one tender in five a ZIP with two more."""
    def pdf(name: str, heading: str) -> File:
        return File(name, "application/pdf", make_pdf([heading, f"Tender {ident}", title,
                                                       f"Reference {reference}", f"File {name}"]))

    files = [pdf("tender-notice.pdf", "Tender notice"), pdf("specifications.pdf", "Specifications")]
    if number % 2 == 0:
        files.append(pdf("price-schedule.pdf", "Price schedule"))
    if number % 5 == 0:
        entries = [pdf("annex-a-site-plan.pdf", "Annex A: site plan"),
                   pdf("annex-b-declaration.pdf", "Annex B: declaration form")]
        files.append(File("annexes.zip", "application/zip", make_zip([(e.name, e.body) for e in entries])))
    return files


def make_zip(entries: list[tuple[str, bytes]]) -> bytes:
    """A ZIP whose bytes depend only on its entries: fixed entry times, fixed attributes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries:
            info = zipfile.ZipInfo(name, date_time=_ZIP_ENTRY_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3            # the same on every platform
            info.external_attr = 0o644 << 16
            archive.writestr(info, body)
    return buffer.getvalue()


def make_pdf(lines: list[str]) -> bytes:
    """A one-page PDF 1.4 that shows these lines, with a correct cross-reference table."""
    text = ["BT", "/F1 12 Tf", "72 770 Td", "16 TL"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        text.append(f"({escaped}) Tj T*")
    text.append("ET")
    stream = "\n".join(text).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode("ascii")
    return bytes(out)
