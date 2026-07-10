# AGENTS.md — economic_report_v2 작업 규칙

## 프로젝트 목적
경제지표 리포트를 정적 HTML로 생성한다.
디자인 원본은 templates/sample_report_v11.html이며 이 디자인 보존이 최우선이다.

## 현재 단계
현재 단계는 루트의 STAGE.md 첫 줄을 기준으로 한다.
현재 작업 단계: 3.1
3.1단계 목표는 BLS CPI 실제 데이터 수집기를 구현하되, canonical payload/HTML 리포트/GitHub Pages에는 아직 연결하지 않는 것이다.

## 절대 규칙
1. templates/sample_report_v11.html은 읽기 전용 원본이다.
   읽기만 허용한다. 수정, 이동, 삭제, 이름변경은 금지한다.

2. 작업용 템플릿은 templates/report.html 하나뿐이다.
   report.html은 sample_report_v11.html을 그대로 복사한 뒤,
   리포트마다 바뀔 텍스트 내용만 placeholder로 치환해 만든다.

3. 디자인 보존:
   - <style> 블록은 여러 개가 있으면 전부 원본과 바이트 단위로 동일해야 한다.
   - CSS 클래스명, id, 태그 구조, 레이아웃, 색상, 다크모드 코드는 수정 금지다.
   - 파일 전체 재포맷 금지. 들여쓰기, 공백, 줄바꿈을 정리하거나 바꾸지 않는다.
   - 허용되는 변경은 오직 태그 사이의 텍스트 내용을 placeholder로 치환하는 것뿐이다.

4. <script> 태그 추가 금지.
   원본에 script가 있으면 한 글자도 건드리지 않는다.

5. API 키, 토큰, 비밀번호를 코드, HTML, JSON, 로그, 커밋 메시지에 쓰지 않는다.

6. 범위 준수:
   - 지시받지 않은 파일 생성, 수정 금지.
   - 지시받지 않은 명령 실행 금지.
   - git init, git add, git commit, 패키지 설치, 외부 라이브러리 설치 금지.
   - 1단계에서는 외부 API, Claude API, GitHub Actions, 실제 데이터 수집기, DB, 서버를 만들지 않는다.
   - Python 표준 라이브러리만 사용한다.

## placeholder 규칙
- 형식은 반드시 영어 대문자 스네이크 케이스만 사용한다.
- 허용 예시: {{REPORT_TITLE}}, {{CPI_ACTUAL}}, {{AI_SUMMARY_HTML}}
- 금지 예시: {{지표명}}, {{report_title}}, {{CpiActual}}
- templates/report.html의 placeholder와 data/sample_payload.json의 키는 1:1로 일치해야 한다.
- placeholder는 태그 사이의 텍스트 위치에만 넣는다.
- 태그명, 클래스명, id, style 속성 값, href 속성 값에는 넣지 않는다.

## 값 형식 규칙
- 일반 키: 순수 텍스트. 빌드 시 HTML 이스케이프해서 삽입한다.
- _HTML로 끝나는 키: <p>...</p> 같은 HTML 조각 허용. 이 값은 이스케이프하지 않고 삽입한다.
- 다문단 해석문은 반드시 _HTML 키를 사용한다.

## 반복 요소 규칙
- 1단계에서는 반복 요소 개수를 원본과 동일하게 고정한다.
- 카드, 표 행, 아코디언 등은 루프를 만들지 않는다.
- 번호 붙은 placeholder를 사용한다.
- 예: {{IND_1_NAME}}, {{IND_2_NAME}}, {{CASE_1_TITLE}}, {{CASE_2_TITLE}}
- Jinja2, for문, 조건문, 템플릿 엔진 구현 금지.

## 파일 구조
허용되는 파일은 아래만이다.

- templates/sample_report_v11.html
- templates/report.html
- data/sample_payload.json
- scripts/build_report.py
- docs/index.html
- docs/reports/sample-report.html
- .gitignore
- AGENTS.md

## 빌드 규칙
scripts/build_report.py는 다음을 반드시 포함한다.

1. data/sample_payload.json 읽기
2. templates/report.html 읽기
3. 일반 키는 html.escape() 적용 후 치환
4. _HTML 키는 원문 그대로 치환
5. 치환 후 \{\{[A-Z0-9_]+\}\} 패턴이 남으면 실패
6. templates/sample_report_v11.html과 templates/report.html의 모든 <style> 블록 비교
7. <style> 블록 개수나 내용이 다르면 실패
8. 스타일 검증을 통과한 경우에만 docs/reports/sample-report.html 생성
9. docs/index.html 생성
10. 성공 시 OK 메시지 출력

## 출력 위치
- 최종 리포트: docs/reports/sample-report.html
- 인덱스 페이지: docs/index.html

## 작업 완료 보고
작업 후 반드시 아래를 보고한다.

1. 생성한 파일 목록
2. 수정한 파일 목록
3. 원본 sample_report_v11.html을 수정하지 않았다는 확인
4. 모든 <style> 블록 자동 검증 결과
5. 실행 명령어
6. 실행 결과
7. 남은 placeholder 검사 결과
8. docs/index.html 링크 확인 결과
