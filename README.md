# data_sync_monitor

SRT 열차 예약 모니터링 도구. **Streamlit 웹 UI** 또는 **로컬 CLI** 두 가지 모드로 실행 가능합니다.

## 설치

```bash
pip install -r requirements.txt
```

## 실행 방법

### 1. Streamlit 모드 (기존과 동일)

```bash
streamlit run data_sync_monitor.py
```

### 2. CLI 모드 (로컬 실행)

1. `config.ini` 파일을 열어 값을 채웁니다.
2. 아래 명령으로 실행합니다.

```bash
python data_sync_monitor.py
```

다른 경로의 설정 파일을 사용하려면:

```bash
python data_sync_monitor.py --config /path/to/my_config.ini
```

## config.ini 설정 항목

| 섹션         | 키            | 설명                    | 예시                 |
| ------------ | ------------- | ----------------------- | -------------------- |
| `[SRT]`      | `USER_ID`     | SRT 로그인 아이디       | `0101234567`         |
| `[SRT]`      | `USER_PASS`   | SRT 로그인 비밀번호     | `mypassword`         |
| `[ROUTE]`    | `SOURCE`      | 출발역                  | `수서`               |
| `[ROUTE]`    | `DESTINATION` | 도착역                  | `동대구`             |
| `[SCHEDULE]` | `DATE`        | 날짜 (YYYYMMDD)         | `20260320`           |
| `[SCHEDULE]` | `START_TIME`  | 시작시간 (HH0000)       | `120000`             |
| `[SCHEDULE]` | `END_TIME`    | 종료시간 (HH0000)       | `230000`             |
| `[SEAT]`     | `TYPE`        | 좌석 타입               | `General / Priority` |
| `[INTERVAL]` | `MIN_SEC`     | 최소 대기 초            | `5`                  |
| `[INTERVAL]` | `MAX_SEC`     | 최대 대기 초            | `10`                 |
| `[TELEGRAM]` | `BOT_TOKEN`   | 텔레그램 봇 토큰 (선택) |                      |
| `[TELEGRAM]` | `CHAT_ID`     | 텔레그램 채팅 ID (선택) |                      |

### 좌석 타입 옵션

- `General / Priority` — 일반실 우선
- `General Only` — 일반실만
- `Special / Priority` — 특실 우선
- `Special Only` — 특실만
