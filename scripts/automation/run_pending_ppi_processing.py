from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.automation import process_ppi_release

def run_pending(root: Path,event_id: str|None=None)->dict[str,Any]:
    releases=list((root/"data/releases/ppi").glob("*/as_released.json")) if (root/"data/releases/ppi").exists() else []
    ids=[path.parent.name for path in releases]
    if event_id: return process_ppi_release.process(root,event_id) if event_id in ids else {"status":"NO_PENDING_PPI_EVENT","commit_paths":[]}
    if not ids:return {"status":"NO_PENDING_PPI_EVENT","commit_paths":[],"external_api_called":False,"external_ai_api_called":False,"cost_mode":"free"}
    if len(ids)>1:return {"status":"MULTIPLE_PENDING_PPI_EVENTS","commit_paths":[]}
    return process_ppi_release.process(root,ids[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-json")
    args = parser.parse_args()
    result = run_pending(PROJECT_ROOT)
    if args.result_json:
        path = Path(args.result_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
