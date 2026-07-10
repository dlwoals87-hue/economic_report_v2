# CPI 실제 리포트 HTML 생성 안내서

## 필요한 입력 파일

리포트 생성에는 같은 `event_id`에 대한 다음 두 파일이 모두 필요하다.

- `data/generated/cpi/{event_id}/canonical_release.json`
- `data/analysis/cpi/{event_id}/cpi-analysis-v1.json`

분석 파일의 `input.canonical_sha256`은 canonical 파일의 실제 SHA-256과 일치해야 한다. 해시 연결이 다르면 `INPUT_INTEGRITY_MISMATCH`로 중단하며 기존 HTML도 수정하지 않는다.

## 실행 명령

```powershell
python scripts/pipelines/build_cpi_release_report.py --event-id US_CPI_2026_06
```

필요한 경우 프로젝트 내부 경로에 한해 `--canonical`, `--analysis`, `--output`을 지정할 수 있다. `..` 경로와 프로젝트 밖 절대경로는 허용하지 않는다.

## Actual As Released 원칙

헤드라인과 근원 CPI의 전월비·전년비는 모두 canonical의 `actual_as_released`와 `previous_as_released`를 사용한다. `actual_current`는 사용하지 않는다. 예상치가 없으면 `미입력`, surprise가 없으면 `산출 불가`로 표시하고 이를 숫자 0이나 방향성 표현으로 바꾸지 않는다.

렌더링 뒤 각 지표 행의 실제·이전·예상·surprise 값을 다시 추출해 canonical 매핑과 일치하는지 검증한다. 하나라도 다르면 HTML을 만들지 않는다.

## 규칙 기반 분석 표시

해석 문장은 `cpi-analysis-v1.json`의 허용 필드에서만 가져온다. 결과에는 다음 사실을 명시한다.

- 분석 방식: 규칙 기반 자동 해석
- 외부 AI API: 사용하지 않음
- 정보 제공 목적이며 투자 조언이 아님

분석 공급자는 `rule_based`, 외부 API 호출은 `false`, 토큰 사용량은 모두 0이어야 한다.

## 데이터 없는 섹션

시장 반응, 자산 가격, 수익률 곡선, 포지셔닝, 유동성, 세부 품목, 과거 사례, 전망 확률처럼 입력에 없는 v11 섹션은 결과에서 제외한다. 분석의 `unsupported_sections`는 다음 문구와 함께 입력 범위 영역에 표시한다.

`해당 데이터는 이번 리포트 입력에 포함되지 않았습니다.`

샘플 시장 수치, 가짜 차트, 시나리오 확률을 대신 보여주지 않는다.

## 샘플 데이터 차단

실제 렌더러는 `data/sample_payload.json`과 `data/canonical_sample_payload.json`을 읽지 않는다. 실제 flat payload는 canonical, 분석 파일, `data/indicator_profiles.json`, 안전한 정적 레이블만 사용한다. 최종 HTML에서 `sample`, `샘플` 및 알려진 샘플 고유 문장을 검사한다.

## 원본 v11 디자인 보호

`templates/sample_report_v11.html`은 읽기 전용 디자인 원본이다. 렌더링 전후 전체 파일 SHA-256을 비교하고, `templates/report.html`의 모든 style 블록이 원본과 정확히 같은지 확인한다. 템플릿에는 script를 추가하지 않으며 실제 HTML에도 외부 JavaScript나 추적 코드를 넣지 않는다.

## Placeholder와 HTML 안전성

최종 HTML에는 `{{...}}`, `${...}`, `__PLACEHOLDER__`, `PLACEHOLDER_`가 남아서는 안 된다. 누락 key나 미사용 payload key가 있으면 생성에 실패한다.

분석 문자열은 모두 HTML escape 처리한다. `script`, `iframe`, `object`, `embed`, event handler 속성 및 `javascript:` URL이 실행 가능한 HTML로 삽입되지 않도록 최종 문서도 재검사한다.

## 기존 HTML 보호

출력은 임시 파일을 만든 뒤 원자적으로 새 파일을 생성한다.

- 출력 없음: `REPORT_CREATED`
- 동일 결과 존재: `ALREADY_UP_TO_DATE`
- 다른 결과 존재: `OUTPUT_CONFLICT`

자동 덮어쓰기와 `--force` 옵션은 제공하지 않는다. 실행 결과에는 event ID, canonical·analysis·template·report SHA-256, 생성 시각을 기록하며 API 키와 절대경로는 기록하지 않는다.

## 현재 발표 전 상태

현재 `US_CPI_2026_06` canonical 파일이 없으므로 정상 상태는 `CANONICAL_RELEASE_NOT_FOUND`이다. 이 경우 종료 코드는 0이고 `docs/reports/US_CPI_2026_06.html`은 생성하지 않는다.

## 다음 자동화 단계와의 관계

이 단계는 이미 생성된 canonical과 무료 분석을 HTML로 변환하는 마지막 단일 책임만 가진다. 후속 자동화는 3.8 처리 결과가 성공하고 두 입력의 해시 연결이 검증된 경우에만 이 명령을 호출해야 한다. GitHub Actions 연결, 인덱스 갱신, 커밋 경로 정책은 별도 단계에서 다룬다.
