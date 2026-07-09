import html
import json
import re
import sys
from pathlib import Path


PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")
STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)


def read_text(path):
    return path.read_text(encoding="utf-8")


def main():
    root = Path(__file__).resolve().parents[1]
    data_path = root / "data" / "sample_payload.json"
    template_path = root / "templates" / "report.html"
    source_path = root / "templates" / "sample_report_v11.html"
    report_path = root / "docs" / "reports" / "sample-report.html"
    index_path = root / "docs" / "index.html"

    payload = json.loads(read_text(data_path))
    template = read_text(template_path)
    source = read_text(source_path)

    source_styles = STYLE_RE.findall(source)
    template_styles = STYLE_RE.findall(template)
    if len(source_styles) != len(template_styles) or source_styles != template_styles:
        print("ERROR: style block mismatch")
        return 1

    template_keys = {match.strip("{}") for match in PLACEHOLDER_RE.findall(template)}
    payload_keys = set(payload)
    missing_keys = sorted(template_keys - payload_keys)
    extra_keys = sorted(payload_keys - template_keys)
    if missing_keys or extra_keys:
        if missing_keys:
            print("ERROR: missing payload keys")
            for key in missing_keys:
                print(key)
        if extra_keys:
            print("ERROR: unused payload keys")
            for key in extra_keys:
                print(key)
        return 1

    rendered = template
    for key, value in payload.items():
        replacement = str(value)
        if not key.endswith("_HTML"):
            replacement = html.escape(replacement)
        rendered = rendered.replace("{{" + key + "}}", replacement)

    remaining = sorted({match.strip("{}") for match in PLACEHOLDER_RE.findall(rendered)})
    if remaining:
        print("ERROR: unresolved placeholders")
        for name in remaining:
            print(name)
        return 1

    if re.search(r"<script\b", rendered, re.IGNORECASE):
        print("ERROR: script tag found")
        return 1

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(rendered, encoding="utf-8")

    index_html = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>경제지표 리포트</title>
</head>
<body>
<h1>경제지표 리포트</h1>
<p><a href="./reports/sample-report.html">샘플 리포트 보기</a></p>
</body>
</html>
"""
    index_path.write_text(index_html, encoding="utf-8")

    print("OK: docs/reports/sample-report.html 생성 완료")
    print("OK: docs/index.html 생성 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
