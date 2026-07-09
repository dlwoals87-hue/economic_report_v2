import html
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from standard_to_flat_payload import build_flat_payload, load_json


STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")
SCRIPT_RE = re.compile(r"<script\b", re.IGNORECASE)

SAMPLES = [
    ("CPI", "canonical_cpi_sample.json", "sample-cpi-report.html"),
    ("PPI", "canonical_ppi_sample.json", "sample-ppi-report.html"),
    ("NFP", "canonical_nfp_sample.json", "sample-nfp-report.html"),
    ("FOMC", "canonical_fomc_sample.json", "sample-fomc-report.html"),
]


def read_text(path):
    return path.read_text(encoding="utf-8")


def validate_style_blocks(source_html, template_html):
    source_blocks = STYLE_RE.findall(source_html)
    template_blocks = STYLE_RE.findall(template_html)
    if len(source_blocks) != len(template_blocks):
        print("ERROR: style block mismatch")
        return False
    if any(source != template for source, template in zip(source_blocks, template_blocks)):
        print("ERROR: style block mismatch")
        return False
    return True


def render_html(template_html, flat_payload):
    rendered = template_html
    for key, value in flat_payload.items():
        replacement = str(value)
        if not key.endswith("_HTML"):
            replacement = html.escape(replacement)
        rendered = rendered.replace("{{" + key + "}}", replacement)
    return rendered


def validate_rendered_html(label, rendered_html, source_html):
    remaining = sorted(set(PLACEHOLDER_RE.findall(rendered_html)))
    if remaining:
        print(f"ERROR: {label} remaining placeholders")
        for placeholder in remaining:
            print(placeholder)
        return False

    if SCRIPT_RE.search(rendered_html):
        print(f"ERROR: {label} script tag detected")
        return False

    if not validate_style_blocks(source_html, rendered_html):
        print(f"ERROR: {label} rendered style block mismatch")
        return False

    return True


def main():
    root = Path(__file__).resolve().parents[1]
    sample_dir = root / "data" / "indicator_samples"
    report_dir = root / "docs" / "reports"
    source_path = root / "templates" / "sample_report_v11.html"
    template_path = root / "templates" / "report.html"
    reference_flat_path = root / "data" / "sample_payload.json"

    source_html = read_text(source_path)
    template_html = read_text(template_path)
    if not validate_style_blocks(source_html, template_html):
        return 1

    reference_flat = load_json(reference_flat_path)
    report_dir.mkdir(parents=True, exist_ok=True)

    for label, sample_name, output_name in SAMPLES:
        sample_path = sample_dir / sample_name
        if not sample_path.exists():
            print(f"ERROR: missing sample file: {sample_path}")
            return 1

        canonical = load_json(sample_path)
        flat_payload = build_flat_payload(canonical, reference_flat)
        if flat_payload is None:
            print(f"ERROR: {label} flat payload conversion failed")
            return 1

        rendered_html = render_html(template_html, flat_payload)
        if not validate_rendered_html(label, rendered_html, source_html):
            return 1

        output_path = report_dir / output_name
        output_path.write_text(rendered_html, encoding="utf-8")
        print(f"OK: {output_path.relative_to(root).as_posix()} 생성 완료")

    return 0


if __name__ == "__main__":
    sys.exit(main())
