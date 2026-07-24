# 무료 데이터 생성 사용법

## 처음 보는 티커를 추가할 때

1. MyQuantPlatform에서 정확한 티커를 검색합니다.
2. 상세 데이터가 없다는 안내 아래 `무료 데이터 생성 요청`을 누릅니다.
3. 열리는 GitHub 화면에서 `Submit new issue`를 누릅니다.
4. `Actions` 탭의 `Update free market data` 작업이 끝날 때까지 기다립니다.
5. GitHub Pages 반영 후 사이트로 돌아와 `생성 후 다시 확인`을 누릅니다.

같은 티커는 두 번째부터 API 호출 없이 저장 파일에서 즉시 열립니다.

## Actions에서 직접 만들기

1. 저장소 상단 `Actions`를 누릅니다.
2. 왼쪽에서 `Update free market data`를 선택합니다.
3. `Run workflow`를 누릅니다.
4. `AAPL, QQQM, SOXQ`처럼 쉼표로 티커를 입력합니다.
5. 다시 `Run workflow`를 누릅니다.

티커 입력을 비워두면 이미 저장된 모든 티커가 갱신됩니다.

## 처음 업로드한 뒤 꼭 확인할 것

GitHub 저장소 `Settings` → `Actions` → `General` 아래의 Workflow permissions에서 `Read and write permissions`를 선택해야 자동 작업이 `data/market` 파일을 저장할 수 있습니다. 저장 후 Actions에서 한 번 수동 실행해 초록색 체크가 뜨는지 확인하세요.

## 비용과 한계

- 유료 시장 데이터 API 키: 필요 없음
- GitHub Pages: 공개 저장소에서 무료
- 표준 GitHub Actions: 공개 저장소에서 무료
- 같은 티커 반복 검색: 횟수 제한 없음
- 처음 보는 티커: 데이터 파일 생성 1회 필요
- 데이터 갱신: 평일 하루 1회 예약

이는 법적·기술적으로 보장된 ‘영원한 무제한 데이터 서비스’가 아닙니다. 공개 공급처나 GitHub 정책이 바뀌면 수집기 또는 실행 주기를 조정해야 합니다.
