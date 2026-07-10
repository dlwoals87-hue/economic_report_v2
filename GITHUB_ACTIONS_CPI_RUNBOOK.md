# GitHub Actions CPI 자동 포착 운영 안내서

## 1. 이 자동화가 하는 일

이 자동화는 CPI 발표 시각 근처에 GitHub Actions에서 실행되어, 포착 가능한 CPI 이벤트가 있는지 확인합니다.
포착 대상이 없으면 아무 파일도 커밋하지 않고 종료합니다.
포착 대상이 있고 BLS 데이터가 목표 기준월까지 게시되었을 때만 최초 발표값을 `as_released.json`으로 저장합니다.

## 2. 예약 실행 시간

예약은 미국 동부시간 `America/New_York` 기준입니다.
서머타임은 GitHub Actions의 timezone 설정을 사용해 처리합니다.

발표 직후 BLS 게시가 몇 분 늦어질 수 있으므로 여러 번 재시도합니다.

- 오전 8시 36분부터 8시 56분까지 5분 간격
- 오전 9시 6분, 9시 21분, 9시 41분
- 오전 10시 11분, 낮 12시 11분

## 3. 수동 실행 방법

1. GitHub 저장소의 Actions 탭으로 이동합니다.
2. `Capture CPI Release` 워크플로를 선택합니다.
3. `Run workflow`를 누릅니다.
4. `event_id`를 비워두면 자동으로 현재 포착 대상 이벤트를 찾습니다.
5. 특정 이벤트를 지정하려면 `US_CPI_2026_06`처럼 입력합니다.
6. `run_tests`를 켜면 수동 실행 전에 오프라인 테스트를 실행합니다.

## 4. 현재 BLS 키

현재 로컬 `BLS_API_KEY`는 BLS에서 invalid로 판정된 상태입니다.
그 키를 GitHub Secrets에 넣지 마세요.

Secret이 없어도 BLS 미등록 모드로 실행할 수 있습니다.
미등록 한도 안의 CPI 4개 시리즈 조회는 이 자동화의 기본 fallback 경로입니다.

## 5. 나중에 유효한 키를 등록하는 위치

유효한 BLS 키를 새로 발급받은 뒤에만 아래 위치에 등록합니다.

1. GitHub 저장소 Settings
2. Secrets and variables
3. Actions
4. New repository secret
5. 이름: `BLS_API_KEY`

키 값은 문서, 코드, 이슈, 커밋 메시지에 기록하지 않습니다.

## 6. 자동 커밋

자동 커밋은 capture 결과가 `CAPTURED`일 때만 실행됩니다.

커밋 대상은 아래 세 종류로 제한됩니다.

- `data/releases/cpi/*/as_released.json`
- `data/raw/bls/cpi/*/retrieved_*.json`
- `data/processed/bls/cpi_latest.json`

커밋 작성자는 GitHub Actions bot입니다.
이는 사람이 직접 만든 커밋이 아니라 자동화가 만든 데이터 포착 커밋이라는 뜻입니다.

## 7. 첫 수동 검증

발표 전 수동 실행에서는 `NO_DUE_EVENT` 또는 `WAITING_FOR_RELEASE`가 정상입니다.
발표 전인데 `as_released.json`이 생긴다면 비정상입니다.

수동 검증에서는 먼저 `event_id`를 비워 자동 선택을 확인하고, 그다음 필요하면 `US_CPI_2026_06`을 직접 넣어 확인합니다.

## 8. 오류별 의미

- `NO_DUE_EVENT`: 지금 포착할 CPI 이벤트가 없습니다.
- `WAITING_FOR_RELEASE`: 지정한 이벤트가 아직 발표 전입니다.
- `DATA_NOT_AVAILABLE_YET`: 발표 시각은 지났지만 BLS 최신 기준월이 아직 목표월이 아닙니다.
- `CAPTURED`: 최초 발표값 포착 파일이 생성되었습니다.
- `ALREADY_CAPTURED`: 이미 `as_released.json`이 있어 다시 저장하지 않았습니다.
- `CAPTURE_WINDOW_EXPIRED`: 발표 후 24시간 포착 가능 시간이 지나 저장을 차단했습니다.
- `MULTIPLE_DUE_EVENTS`: 동시에 여러 이벤트가 포착 대상으로 잡혀 자동 선택을 중단했습니다.

## 9. push 권한 오류 시 확인

자동 커밋 push 권한 오류가 나면 아래 설정을 확인합니다.

1. GitHub 저장소 Settings
2. Actions
3. General
4. Workflow permissions
5. `Read and write permissions` 선택

권한을 바꾼 뒤 다시 수동 실행으로 확인합니다.

## 10. 주의사항

- workflow는 `main` 브랜치에 있어야 예약 실행됩니다.
- 공개 저장소에서 60일간 활동이 없으면 예약 workflow가 비활성화될 수 있습니다.
- workflow 파일을 임의로 삭제하지 마세요.
- 포착 성공 파일인 `as_released.json`을 수동으로 수정하지 마세요.
- 자동화가 만든 커밋에는 API 키나 개인 인증정보가 포함되면 안 됩니다.
