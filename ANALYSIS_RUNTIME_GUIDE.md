# 경제 해석 운영 안내서

## 1. 이 기능이 하는 일

발표 후 생성되는 CPI `canonical_release.json`을 검증하고, 결정적 수치 사실을 Python으로 계산한 뒤 선택된 provider가 해석을 만든다. 기본 provider는 외부 API를 사용하지 않는 `rule_based`다. 모든 결과는 동일한 스키마와 정확성 검증을 통과한 뒤 `cpi-analysis-v1.json`으로 저장된다.

## 2. provider 우선순위

선택 우선순위는 다음과 같다.

1. CLI의 `--provider`
2. 환경변수 `ANALYSIS_PROVIDER`
3. `rule_based`

지원값은 `rule_based`, `github_models`, `openai`다. `OPENAI_API_KEY`가 있어도 OpenAI가 자동 선택되지는 않는다.

비용 없이 실행하는 권장 명령:

```powershell
python scripts/analysis/generate_cpi_analysis.py --event-id US_CPI_2026_06 --provider rule_based
```

## 3. AI와 Python의 역할

Python이 하는 일:

- 실제값과 직전값의 결정적 매핑
- 변화량과 momentum 방향 계산
- surprise 재검산
- evidence path, 숫자, 시장 반응 표현 검증

provider가 하는 일:

- 검증된 facts를 한국어 해석 구조로 변환
- 정책 신호와 근거 및 한계 정리

provider는 facts를 수정하거나 없는 숫자를 만들 수 없다.

## 4. rule_based

- 기본 provider
- 외부 API 호출 0회
- API 키와 토큰 불필요
- actual, previous, momentum, surprise를 정해진 규칙으로 해석
- 기존 AI 결과와 동일한 엄격 스키마 및 후검증 적용
- 비용 0원 운영을 보장하려면 `--provider rule_based`를 사용

## 5. github_models

`github_models`는 무료 AI 연결을 위한 선택 구조다. endpoint와 모델은 운영 환경에서 다음 변수로 명시해야 하며 코드에 임의 기본값을 두지 않는다.

- `GITHUB_TOKEN`
- `GITHUB_MODELS_MODEL`
- `GITHUB_MODELS_ENDPOINT`

현재 단계는 요청 생성, 응답 파싱, mock transport까지만 구현하며 실제 통신은 활성화하지 않는다. 토큰, 구성, 무료 한도, 네트워크, 모델, 응답 검증 문제가 있으면 기본적으로 `rule_based`로 전환한다.

## 6. 선택적 OpenAI

OpenAI Responses API 구현은 선택 기능으로 유지한다. 다음 두 조건이 모두 충족돼야 호출 경로에 들어간다.

1. `--provider openai` 또는 `ANALYSIS_PROVIDER=openai`
2. `OPENAI_API_KEY` 존재

키가 있다는 이유만으로 자동 선택하지 않는다. 키가 없으면 기본 설정에서는 결제나 키 발급을 요구하지 않고 `rule_based`로 전환한다. OpenAI 모델은 `OPENAI_MODEL`로 변경할 수 있다.

## 7. fallback

`--allow-rule-fallback`은 기본 활성화 상태다. 외부 provider 실패 시 최종 결과의 provider 메타데이터에 요청 provider, 실제 사용 provider, 외부 호출 여부, fallback 사유를 기록한다.

fallback을 명시적으로 끄려면 다음 옵션을 사용한다.

```powershell
--no-rule-fallback
```

## 8. 실행 전 필요한 파일

기본 입력:

`data/generated/cpi/{event_id}/canonical_release.json`

기본 출력:

`data/analysis/cpi/{event_id}/cpi-analysis-v1.json`

canonical 파일이 없으면 `CANONICAL_RELEASE_NOT_FOUND`로 정상 대기하며 provider 호출, 키 확인, 출력 생성이 모두 발생하지 않는다.

## 9. 분석 파일의 감사 정보

분석 파일에는 canonical, 프롬프트, 스키마 SHA-256과 요청 provider, 실제 provider, 모델, 응답 ID, 외부 호출 여부, fallback 사유, 토큰 사용량을 기록한다. 키, 토큰, Authorization 헤더, 전체 원본 API 응답, 모델 내부 reasoning은 저장하지 않는다.

## 10. 비용과 보안

- 자동화의 권장 기본은 `rule_based`다.
- 유료 OpenAI는 명시적으로 선택하기 전에는 호출되지 않는다.
- 키와 토큰을 로그, JSON, HTML, 저장소에 기록하지 않는다.
- 외부 provider를 선택할 때는 무료 한도와 실제 사용량을 별도로 확인한다.
