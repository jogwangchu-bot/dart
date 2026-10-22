"""All companies, official-record snapshots and API data here are synthetic."""
import io
import json
from datetime import date
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook

from pit_dart.core import digest
from pit_dart.reviews import Reviews

ASOF = date(2019, 9, 18)
CORP = "00000001"


def archive(files):
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as zipped:
        for name, content in files.items():
            zipped.writestr(name, content)
    return stream.getvalue()


def workbook(path, rows=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    sheet = book.active
    sheet.append(["순번", "원본 종목명", "종목코드", "2019 검색명", "변경", "미래정보"])
    for row in rows or [(1, "CURRENT_NAME_2026", "000001", "Historical Synthetic", "관리자힌트", "FUTURE_DELIST_2026")]:
        sheet.append(row)
    book.save(path)
    book.close()
    return path


def disclosure(number, title, **extra):
    return {"corp_code": CORP, "corp_name": "CURRENT_NAME_2026", "stock_code": "000001", "report_nm": title,
            "rcept_no": number, "rcept_dt": number[:8], "flr_nm": "Historical Synthetic", "rm": "FUTURE_CORRECTION_2026", **extra}


ANNUAL = disclosure("20190329000001", "사업보고서 (2018.12)")
INTERIM = disclosure("20190814000001", "반기보고서 (2019.06)")


def document(number, kind="annual", company=CORP, extra=""):
    xml = (f'<DOCUMENT><RECEIPT-NO>{number}</RECEIPT-NO><COMPANY-NAME AREGCIK="{company}">Historical Synthetic</COMPANY-NAME>'
           f'<DOCUMENT-NAME ACODE="{"11011" if kind == "annual" else "11012"}">보고서</DOCUMENT-NAME>'
           '<TABLE><TR><TH>항목</TH><TH>백만원</TH></TR><TR><TD>매출</TD><TD>1,234</TD></TR></TABLE>'
           f'<P>2030년 사업계획</P>{extra}</DOCUMENT>').encode()
    return archive({"report.xml": xml})


class FakeClient:
    def __init__(self, records=None):
        self.records = [ANNUAL, INTERIM] if records is None else records
        self.bodies = {ANNUAL["rcept_no"]: document(ANNUAL["rcept_no"]), INTERIM["rcept_no"]: document(INTERIM["rcept_no"], "interim")}
        self.list_calls, self.document_calls, self.corporation_calls = [], [], 0

    def corporations(self):
        self.corporation_calls += 1
        return archive({"CORPCODE.xml": b'<result><list><corp_code>00000001</corp_code><corp_name>CURRENT_NAME_2026</corp_name><stock_code>000001</stock_code></list></result>'})

    def list(self, **parameters):
        self.list_calls.append(parameters)
        rows = [item for item in self.records if parameters["bgn_de"] <= item["rcept_dt"] <= parameters["end_de"]]
        if not rows:
            return {"status": "013"}
        offset = (parameters["page_no"] - 1) * 100
        return {"status": "000", "total_count": len(rows), "total_page": (len(rows) + 99) // 100,
                "page_count": 100, "page_no": parameters["page_no"], "list": rows[offset:offset+100]}

    def document(self, number):
        self.document_calls.append(number)
        return self.bodies[number]


def reviews(root, client, *, approved=True):
    evidence_dir = root / "config" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    file = evidence_dir / "SYNTHETIC-official-record.txt"
    file.write_text("SYNTHETIC fixture only. Not a real official verification.")
    base = {"reviewed_by": "Synthetic Test Reviewer", "reviewed_at": "2026-10-21",
            "evidence": [{"path": str(file.relative_to(root)), "sha256": digest(file.read_bytes()),
                          "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20190814000001", "publication_date": "2019-08-14"}]}
    data = {"identities": {}, "documents": {}}
    if approved:
        data["identities"]["000001"] = {**base, "asof": str(ASOF), "corp_code": CORP, "historical_name": "Historical Synthetic",
                                          "stock_code_continuity_checked": True, "corporate_actions_checked": True, "historical_name_checked": True}
        for row in client.records:
            if row["rcept_no"] not in client.bodies:
                continue
            kind = "annual" if "사업보고서" in row["report_nm"] else "interim"
            period = "2018-12" if kind == "annual" else "2019-06"
            data["documents"][row["rcept_no"]] = {**base, "asof": str(ASOF), "corp_code": CORP, "stock_code": "000001",
                "receipt_no": row["rcept_no"], "reporting_period": period, "document_type": kind, "raw_sha256": digest(client.bodies[row["rcept_no"]]),
                "receipt_checked": True, "corporation_checked": True, "period_checked": True, "historical_version_checked": True,
                "full_content_checked": True, "attachments_checked": True, "missing_attachments": []}
        data["history"] = {**base, "available_from": "1999-01-01", "earliest_available_checked": True}
    path = root / "config" / "reviews.json"
    path.write_text(json.dumps(data))
    return Reviews(root, path, ASOF)
