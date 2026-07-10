# 무료 경제 해석 운영 안내서

## 기본 운영

기본 provider는 `rule_based`다. 외부 API와 키 없이 항상 작동하며, canonical CPI 입력이 준비돼 있으면 비용 0원으로 분석 JSON을 생성한다.

```powershell
python scripts/analysis/generate_cpi_analysis.py --event-id US_CPI_2026_06 --provider rule_based
```

비용 0원을 확실히 보장해야 하는 실행과 실제 자동화에서는 위 설정을 권장한다.

## 무료 AI는 선택 기능

`github_models`는 무료 AI 품질 개선을 위한 선택 provider다. 현재 단계에서는 endpoint나 모델을 임의로 고정하지 않고 환경변수 기반 요청 구조와 mock 테스트만 제공한다.

```powershell
python scripts/analysis/generate_cpi_analysis.py --event-id US_CPI_2026_06 --provider github_models
```

연결할 때 필요한 설정:

- `GITHUB_TOKEN`
- `GITHUB_MODELS_MODEL`
- `GITHUB_MODELS_ENDPOINT`

향후 실제 연결 전에는 공식 endpoint와 지원 모델, 무료 한도, 데이터 저장 정책, Structured Outputs 호환성을 확인해야 한다.

## fallback 작동 방식

무료 AI 토큰이나 설정이 없거나, 무료 한도 초과, 네트워크 오류, 모델 오류, 응답 검증 실패가 발생하면 `rule_based`가 분석을 대신 생성한다. 최종 JSON에는 요청 provider와 fallback 사유가 남는다.

fallback은 기본 활성화다. 오류를 그대로 받고 분석 생성을 중단해야 할 때만 `--no-rule-fallback`을 사용한다.

## 유료 OpenAI

OpenAI는 기본 비활성화 상태다. `OPENAI_API_KEY`가 있어도 자동 호출되지 않는다. 사용자가 `--provider openai`를 명시하고 키가 있을 때만 유료 호출 경로가 허용된다. 키가 없으면 기본적으로 `rule_based`로 전환한다.

## 정확성 안전장치

모든 provider 결과에 다음 검증을 동일하게 적용한다.

- Python이 actual, previous, change, momentum facts 생성
- canonical surprise 재검산
- 실제 facts evidence path만 허용
- facts에 있는 `%`, `%p` 숫자만 허용
- 예상치가 없을 때 상회·하회 표현 거부
- 입력에 없는 시장 반응 표현 거부
- 엄격한 JSON Schema와 `additionalProperties: false`
- 기존 분석 파일 덮어쓰기 금지

## 보안

API 키와 토큰은 환경변수에서만 읽고 코드, 로그, 분석 JSON, HTML에 저장하지 않는다. 기본 `rule_based` 실행은 어떤 키나 토큰도 확인하지 않는다.
