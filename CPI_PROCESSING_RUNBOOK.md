# CPI 발표 후 무료 처리 운영 안내서

## 1. 전체 처리 순서

통합 처리기는 다음 순서를 하나의 명령으로 실행한다.

1. `data/calendar/events.json` 검증
2. `data/releases/cpi/{event_id}/as_released.json` 존재 및 무결성 확인
3. 기존 canonical 생성기로 `canonical_release.json` 생성 또는 검증
4. 기존 분석 파이프라인의 `rule_based` provider로 무료 분석 생성 또는 검증
5. release, canonical, analysis 사이의 SHA-256 연결 확인

실행 예:

```powershell
python scripts/automation/process_cpi_release.py --event-id US_CPI_2026_06 --provider rule_based
```

구조화된 처리 결과가 필요하면 프로젝트 내부 상대경로를 지정한다.

```powershell
python scripts/automation/process_cpi_release.py --event-id US_CPI_2026_06 --result-json process-result.json
```

## 2. as_released가 없을 때

발표 파일이 없으면 `RELEASE_NOT_CAPTURED`로 정상 종료한다. canonical과 analysis를 만들지 않고, 외부 API나 API 키를 확인하지 않는다. `created_paths`와 `commit_paths`도 비어 있다.

## 3. canonical의 역할

canonical은 불변의 최초 발표 파일을 분석에 필요한 공통 구조로 변환한다. actual과 previous, 수동 입력 expected, 결정적 surprise를 구분하고 release SHA-256을 `source.release_capture_sha256`에 기록한다.

통합 처리기는 `build_cpi_release_canonical.py`의 기존 로직을 그대로 재사용한다. 기존 canonical이 현재 release와 다르면 덮어쓰지 않고 `INTEGRITY_CHECK_FAILED`로 중단한다.

## 4. rule_based 분석의 역할

분석 단계는 외부 API를 사용하지 않는 `rule_based`만 실행한다. Python이 만든 facts를 바탕으로 CPI 흐름과 기계적 정책 신호를 생성하며, 다음 검증을 그대로 적용한다.

- actual과 previous 결정적 매핑
- expected와 surprise 일관성
- 엄격한 JSON Schema
- 실제 facts evidence path
- `%` 및 `%p` 숫자 화이트리스트
- 예상치가 없을 때 상회·하회 표현 차단
- 근거 없는 시장 반응 표현 차단

## 5. 외부 API와 비용이 없는 이유

3.8 통합 처리기는 provider를 `rule_based`로 고정한다. `github_models` 또는 `openai`를 지정하면 실제 호출 전에 `EXTERNAL_PROVIDER_DISABLED`로 차단한다. 따라서 토큰 사용량은 모두 0이고 처리 비용도 0원이다.

## 6. 상태별 의미

- `RELEASE_NOT_CAPTURED`: 발표 파일이 없어 정상 대기
- `PROCESSED`: canonical과 무료 분석을 생성하고 연결 검증 완료
- `CANONICAL_ONLY_RESUMED`: 기존 canonical을 검증하고 analysis만 생성
- `ALREADY_PROCESSED`: 두 파생 파일과 해시 연결이 이미 유효함
- `CALENDAR_INVALID`: calendar 검증 실패 또는 event_id 불일치
- `INTEGRITY_CHECK_FAILED`: release 또는 canonical SHA 및 연결 불일치
- `INCONSISTENT_DERIVED_STATE`: canonical 없이 analysis가 존재하는 등 파생 상태가 모순됨
- `ANALYSIS_FAILED`: analysis 구조, facts, rule_based 내용 또는 후검증 실패

## 7. 재실행과 덮어쓰기 방지

canonical과 analysis가 모두 존재하면 파일을 다시 생성하지 않는다. 현재 release에서 계산한 canonical과 기존 파일이 같은지 확인하고, 기존 analysis의 canonical SHA, release SHA, facts, provider, token usage, prompt/schema hash, rule_based 내용을 검증한다.

검증을 통과하면 `ALREADY_PROCESSED`를 반환하며 두 파일의 내용과 수정 시각을 바꾸지 않는다. 불일치 파일을 자동 삭제하거나 덮어쓰지 않는다.

## 8. SHA-256 연결 검증

연결은 다음 두 단계다.

```text
as_released 검증 SHA-256
  -> canonical.source.release_capture_sha256

canonical 파일 SHA-256
  -> analysis.input.canonical_sha256
```

analysis의 `input.release_capture_sha256`도 canonical의 release SHA와 같아야 한다. 하나라도 다르면 처리 성공으로 판정하지 않는다.

## 9. 생성되는 두 파일

처리가 처음 성공하면 다음 두 파일만 `created_paths`와 `commit_paths`에 포함된다.

- `data/generated/cpi/{event_id}/canonical_release.json`
- `data/analysis/cpi/{event_id}/cpi-analysis-v1.json`

canonical이 이미 있으면 analysis 파일만 포함되고, 둘 다 유효하게 존재하면 목록은 비어 있다. release, raw snapshot, calendar는 수정하지 않는다.

## 10. 다음 HTML 단계와의 관계

3.8은 데이터와 무료 해석 JSON까지 준비하는 단계다. HTML 생성이나 템플릿 연결은 수행하지 않는다. 다음 HTML 단계에서는 검증된 canonical과 analysis를 읽기 전용 입력으로 사용해야 한다.
