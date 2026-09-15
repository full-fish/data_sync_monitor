import sys
import os
import platform
import subprocess
import configparser
import asyncio
import random
import json
import time
from pathlib import Path
from datetime import datetime

import requests as _requests

try:
    from pykorail import (
        AdultPassenger,
        Korail,
        KorailError,
        NeedToLoginError,
        NetFunnelError,
        NoResultsError,
        PastDepartureError,
        SoldOutError,
        TransportError,
    )
    from pykorail.device import profile_by_id, random_profile
    from pykorail.options import ReserveOption, TrainType
except ImportError:
    print("[ERROR] pykorail 패키지가 필요합니다: pip install pykorail")
    raise


# ============================================================
# 공통 상수 / 유틸
# ============================================================

DEVICE_ID_FILE = Path(__file__).with_name(".korail_device_id")

NODE_LIST = [
    "서울",
    "용산",
    "광명",
    "천안아산",
    "오송",
    "대전",
    "김천(구미)",
    "동대구",
    "신경주",
    "울산(통도사)",
    "부산",
    "익산",
    "정읍",
    "광주송정",
    "목포",
    "전주",
    "진영",
    "창원중앙",
    "마산",
    "진주",
    "순천",
    "여수EXPO",
    "나주",
    "공주",
    "포항",
]

RESERVE_OPTION_MAP = {
    "General / Priority": "GENERAL_FIRST",
    "General Only": "GENERAL_ONLY",
    "Special / Priority": "SPECIAL_FIRST",
    "Special Only": "SPECIAL_ONLY",
}

TRAIN_TYPE_MAP = {
    "KTX": TrainType.KTX,
    "ALL": TrainType.ALL,
}


def play_success_sound(repeat: int = 3):
    """예약 성공 시 알림 사운드 재생 (macOS / Windows / Linux)"""
    system = platform.system()
    try:
        for _ in range(repeat):
            if system == "Darwin":
                subprocess.Popen(
                    ["afplay", "/System/Library/Sounds/Glass.aiff"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif system == "Windows":
                import winsound

                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            else:
                print("\a", end="", flush=True)
            time.sleep(0.5)
    except Exception:
        print("\a", end="", flush=True)


async def _send_telegram(token: str, chat_id: str, text: str) -> None:
    """requests를 executor에서 호출해 텔레그램 메시지 전송"""
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: _requests.post(
                url,
                json={"chat_id": chat_id, "text": text},
                timeout=10,
            ),
        )
    except Exception as e:
        print(f"[WARN] 텔레그램 전송 실패: {e}")


def _is_streamlit() -> bool:
    """현재 Streamlit 런타임 안에서 실행 중인지 판별"""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


def _normalize_time_hhmm(value: str, field_name: str) -> str:
    """HHMM 또는 HHMMSS 입력을 HHMM으로 정규화"""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) == 6:
        digits = digits[:4]
    if len(digits) != 4:
        raise ValueError(f"{field_name} 값은 HHMM 또는 HHMMSS 형식이어야 합니다: {value}")
    hh = int(digits[:2])
    mm = int(digits[2:4])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"{field_name} 값의 시/분 범위가 올바르지 않습니다: {value}")
    return digits


def _default_reserve_option():
    return getattr(ReserveOption, "GENERAL_FIRST")


def _resolve_reserve_option(label: str):
    attr_name = RESERVE_OPTION_MAP.get(label, "GENERAL_FIRST")
    return getattr(ReserveOption, attr_name, _default_reserve_option())


def _load_device_profile():
    """기기 프로파일을 재사용해 로그인 안정성 향상"""
    saved_id = None
    if DEVICE_ID_FILE.exists():
        try:
            saved_id = json.loads(DEVICE_ID_FILE.read_text(encoding="utf-8")).get("id")
        except Exception:
            saved_id = None

    profile = (profile_by_id(saved_id) if saved_id else None) or random_profile()
    DEVICE_ID_FILE.write_text(json.dumps({"id": profile.id}), encoding="utf-8")
    return profile


def _login_with_retry(user_id: str, user_pw: str, tries: int = 5) -> Korail:
    profile = _load_device_profile()
    for i in range(1, tries + 1):
        try:
            return Korail.logged_in(user_id, user_pw, device_profile=profile)
        except Exception as e:
            if i == tries:
                raise
            print(f"[WARN] 로그인 실패({i}/{tries}), 5초 후 재시도: {type(e).__name__}: {e}")
            time.sleep(5)
    raise AssertionError("unreachable")


def _safe_relogin(client: Korail, user_id: str, user_pw: str):
    try:
        client.login(user_id, user_pw)
    except Exception as e:
        print(f"[WARN] 재로그인 실패, 다음 루프에서 재시도: {type(e).__name__}: {e}")


def _build_depart_after(date_str: str, start_hhmm: str) -> datetime:
    return datetime.strptime(date_str + start_hhmm, "%Y%m%d%H%M")


def _candidate_trains(
    client: Korail,
    src_node: str,
    dst_node: str,
    depart_after: datetime,
    end_hhmm: str,
    train_type,
    include_waiting_list: bool,
):
    trains = client.trains.search(
        src_node,
        dst_node,
        depart_after=depart_after,
        train_type=train_type,
        include_waiting_list=include_waiting_list,
    )
    end_hhmmss = end_hhmm + "00"
    return [t for t in trains if getattr(t, "dep_time", "999999") <= end_hhmmss]


def _train_number(train) -> str:
    return str(getattr(train, "train_no", getattr(train, "train_number", "-")))


def _train_dep_time(train) -> str:
    dep_time = str(getattr(train, "dep_time", ""))
    if len(dep_time) >= 4:
        return dep_time[:2] + ":" + dep_time[2:4]
    return dep_time or "-"


def _reservation_ref(reservation) -> str:
    for attr in ("reservation_number", "rsv_id", "id"):
        value = getattr(reservation, attr, None)
        if value:
            return str(value)
    return str(reservation)


def _try_reserve_first(
    client: Korail,
    trains: list,
    adults: int,
    reserve_option,
):
    passengers = [AdultPassenger(adults)]
    last_error = None

    for train in trains:
        try:
            reservation = client.reservations.create(
                train,
                passengers=passengers,
                option=reserve_option,
            )
            return train, reservation, None
        except SoldOutError:
            continue
        except KorailError as e:
            last_error = str(e)
            continue
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            continue

    return None, None, last_error


# ============================================================
# CLI (로컬) 모드
# ============================================================
def _load_config(path: str = "config.ini") -> dict:
    if not os.path.exists(path):
        print(f"[ERROR] 설정 파일을 찾을 수 없습니다: {path}")
        print("        config.ini 파일을 생성한 뒤 값을 채워주세요.")
        sys.exit(1)

    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")

    seat_type_str = cfg.get("SEAT", "TYPE", fallback="General / Priority").strip()
    if seat_type_str not in RESERVE_OPTION_MAP:
        print(f"[ERROR] 알 수 없는 좌석 타입: {seat_type_str}")
        print(f"        사용 가능: {', '.join(RESERVE_OPTION_MAP.keys())}")
        sys.exit(1)

    bot_token = cfg.get("TELEGRAM", "BOT_TOKEN", fallback="").strip()
    chat_id_val = cfg.get("TELEGRAM", "CHAT_ID", fallback="").strip()

    user_section = "KORAIL" if cfg.has_section("KORAIL") else "SRT"

    date_str = cfg.get("SCHEDULE", "DATE").strip()
    start_hhmm = _normalize_time_hhmm(
        cfg.get("SCHEDULE", "START_TIME", fallback="0900").strip(),
        "START_TIME",
    )
    end_hhmm = _normalize_time_hhmm(
        cfg.get("SCHEDULE", "END_TIME", fallback="1000").strip(),
        "END_TIME",
    )

    train_type_label = cfg.get("SEARCH", "TRAIN_TYPE", fallback="KTX").strip().upper()
    if train_type_label not in TRAIN_TYPE_MAP:
        train_type_label = "KTX"

    include_waiting_list = cfg.getboolean(
        "SEARCH", "INCLUDE_WAITING_LIST", fallback=False
    )

    return {
        "user_id": cfg.get(user_section, "USER_ID").strip(),
        "user_pw": cfg.get(user_section, "USER_PASS").strip(),
        "src_node": cfg.get("ROUTE", "SOURCE", fallback="서울").strip(),
        "dst_node": cfg.get("ROUTE", "DESTINATION", fallback="동대구").strip(),
        "date_str": date_str,
        "start_hhmm": start_hhmm,
        "end_hhmm": end_hhmm,
        "reserve_option": _resolve_reserve_option(seat_type_str),
        "seat_label": seat_type_str,
        "min_sec": cfg.getint("INTERVAL", "MIN_SEC", fallback=10),
        "max_sec": cfg.getint("INTERVAL", "MAX_SEC", fallback=15),
        "adults": cfg.getint("PASSENGER", "ADULTS", fallback=1),
        "train_type": TRAIN_TYPE_MAP[train_type_label],
        "train_type_label": train_type_label,
        "include_waiting_list": include_waiting_list,
        "bot_token": bot_token,
        "chat_id": chat_id_val,
        "noti_ready": bool(bot_token and chat_id_val),
    }


async def _cli_process(conf: dict):
    user_id = conf["user_id"]
    user_pw = conf["user_pw"]
    src_node = conf["src_node"]
    dst_node = conf["dst_node"]
    token = conf["bot_token"] if conf["noti_ready"] else ""
    chat_id = conf["chat_id"] if conf["noti_ready"] else ""

    print("=" * 60)
    print("  KTX Monitor v2.0  -  CLI Mode")
    print("=" * 60)
    print(f"  User      : {user_id}")
    print(f"  Route     : {src_node} -> {dst_node}")
    print(f"  Date      : {conf['date_str']}")
    print(f"  Time      : {conf['start_hhmm']} ~ {conf['end_hhmm']}")
    print(f"  Seat      : {conf['seat_label']}")
    print(f"  TrainType : {conf['train_type_label']}")
    print(f"  Adults    : {conf['adults']}")
    print(f"  Waiting   : {'ON' if conf['include_waiting_list'] else 'OFF'}")
    print(f"  Delay     : {conf['min_sec']}s ~ {conf['max_sec']}s")
    print(f"  Notify    : {'ON' if conf['noti_ready'] else 'OFF'}")
    print("=" * 60)

    try:
        client = _login_with_retry(user_id, user_pw)
        print("[INFO] KORAIL 로그인 성공")
    except Exception as e:
        print(f"[ERROR] KORAIL 로그인 실패: {e}")
        return

    if conf["noti_ready"]:
        start_msg = (
            f"📡 KTX Monitor Started\n"
            f"👤 User: {user_id}\n"
            f"🛤 Route: [{src_node} -> {dst_node}]\n"
            f"🕒 Window: {conf['date_str']} {conf['start_hhmm']}~{conf['end_hhmm']}"
        )
        await _send_telegram(token, chat_id, start_msg)
        print("[INFO] 텔레그램 시작 알림 전송 완료")

    flag = False
    loop_count = 0
    depart_after = _build_depart_after(conf["date_str"], conf["start_hhmm"])

    try:
        while not flag:
            loop_count += 1
            now_ts = datetime.now().strftime("%H:%M:%S")
            print(f"\n🔄  Sync Loop #{loop_count}  ({now_ts})")

            try:
                items = _candidate_trains(
                    client,
                    src_node,
                    dst_node,
                    depart_after,
                    conf["end_hhmm"],
                    conf["train_type"],
                    conf["include_waiting_list"],
                )
            except NoResultsError:
                items = []
            except PastDepartureError:
                print("[ERROR] 검색 시작 시각이 이미 지났습니다. 종료합니다.")
                return
            except NeedToLoginError:
                print("[WARN] 세션 만료, 재로그인 시도")
                _safe_relogin(client, user_id, user_pw)
                continue
            except (NetFunnelError, TransportError) as e:
                print(f"[WARN] 네트워크/대기열 오류: {e}")
                items = []
            except KorailError as e:
                print(f"[WARN] 검색 중 오류: {e}")
                items = []
            except Exception as e:
                print(f"[WARN] 예상치 못한 검색 오류: {type(e).__name__}: {e}")
                items = []

            print(f"  후보 열차 {len(items)}개")
            print("-" * 55)
            print("   TIME   |  TRAIN  |    STATUS")
            print("-" * 55)

            for item in items:
                print(f" {_train_dep_time(item):>7} | {_train_number(item):^7} | 🟢 AVAILABLE")

            if items:
                print(f"\n🔍 Target Detected [ID:{_train_number(items[0])}]! Acquiring...")
                target_train, reservation, reserve_err = _try_reserve_first(
                    client,
                    items,
                    conf["adults"],
                    conf["reserve_option"],
                )

                if reservation:
                    ref_code = _reservation_ref(reservation)
                    success_msg = (
                        f"🎉 KTX 예약 성공!\n"
                        f"👤 User: {user_id}\n"
                        f"🚆 Train: {_train_number(target_train)} ({_train_dep_time(target_train)})"
                    )
                    print("\n" + "=" * 60)
                    print(success_msg)
                    print(f"🎫 Ref Code: {ref_code}")
                    print("=" * 60)

                    play_success_sound()
                    await _send_telegram(token, chat_id, success_msg)
                    await _send_telegram(token, chat_id, f"🎫 Ref Code: {ref_code}")

                    flag = True
                    break

                if reserve_err:
                    print(f"[WARN] 예약 시도 실패: {reserve_err}")

            sleep_time = random.uniform(conf["min_sec"], conf["max_sec"])
            print(f"  ⏳ 대기 중: {sleep_time:.1f}s")
            await asyncio.sleep(sleep_time)
    finally:
        try:
            client.close()
        except Exception:
            pass

    if flag:
        print("\n✅  Process Completed.")


def run_cli():
    ini_path = "config.ini"
    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            ini_path = sys.argv[idx + 1]

    conf = _load_config(ini_path)
    asyncio.run(_cli_process(conf))


# ============================================================
# Streamlit 모드
# ============================================================
def run_streamlit():
    import streamlit as st

    st.set_page_config(page_title="KTX Monitor", page_icon="🚄")

    if "password_correct" not in st.session_state:

        def check_password():
            if st.session_state.password_input == st.secrets["APP_PASSWORD"]:
                st.session_state.password_correct = True
                del st.session_state.password_input
            else:
                st.error("비밀번호가 틀렸습니다. 다시 시도해주세요.")

        col1, col2, col3 = st.columns([1, 4, 1])

        with col2:
            st.image(
                "yuri6.jpeg",
                caption="유리 파리 쥬리",
                use_container_width=True,
            )

            st.title("🔐 Access Restricted")
            st.caption("Enter access key.")

            st.text_input(
                "비밀번호 입력",
                type="password",
                on_change=check_password,
                key="password_input",
            )

        st.stop()

    st.sidebar.header("System Access")
    secret_login = st.secrets["KORAIL"] if "KORAIL" in st.secrets else st.secrets.get("SRT", {})
    default_uid = secret_login.get("USER_ID", "")
    default_upw = secret_login.get("USER_PASS", "")

    user_id = st.sidebar.text_input("KORAIL ID", value=default_uid)
    user_pw = st.sidebar.text_input("KORAIL Password", value=default_upw, type="password")

    try:
        bot_token = st.secrets["TELEGRAM"]["BOT_TOKEN"]
        chat_id = st.secrets["TELEGRAM"]["CHAT_ID"]
        noti_ready = True
    except Exception:
        noti_ready = False
        st.sidebar.warning("Notification config missing.")

    st.title("KTX Monitor v2.0")
    st.caption("Real-time KTX reservation dashboard")

    default_src_idx = NODE_LIST.index("서울") if "서울" in NODE_LIST else 0
    default_dst_idx = NODE_LIST.index("동대구") if "동대구" in NODE_LIST else 1

    col1, col2 = st.columns(2)
    with col1:
        src_node = st.selectbox("Source Node", NODE_LIST, index=default_src_idx)
        dst_node = st.selectbox("Target Node", NODE_LIST, index=default_dst_idx)

    with col2:
        today = datetime.now().date()
        target_date = st.date_input("Target Date", today)
        date_str = target_date.strftime("%Y%m%d")

        time_options = [f"{i:02d}00" for i in range(24)]
        time_display = [f"{i:02d}:00" for i in range(24)]

        start_idx = st.selectbox(
            "Start Time Range",
            range(len(time_options)),
            format_func=lambda x: time_display[x],
            index=12,
        )
        start_hhmm = time_options[start_idx]

        end_idx = st.selectbox(
            "End Time Range",
            range(len(time_options)),
            format_func=lambda x: time_display[x],
            index=23,
        )
        end_hhmm = time_options[end_idx]

    col3, col4 = st.columns(2)
    with col3:
        config_choice = st.radio(
            "Seat Preference",
            list(RESERVE_OPTION_MAP.keys()),
            horizontal=True,
        )
        reserve_option = _resolve_reserve_option(config_choice)

    with col4:
        train_type_label = st.selectbox("Train Type", list(TRAIN_TYPE_MAP.keys()), index=0)
        train_type = TRAIN_TYPE_MAP[train_type_label]
        include_waiting_list = st.checkbox("Include Waiting List", value=False)
        adults = st.number_input("Adults", min_value=1, max_value=9, value=1, step=1)

    st.write("Request Interval Settings (sec)")
    interval_range = st.slider(
        "Set random interval for stability",
        min_value=1,
        max_value=300,
        value=(10, 15),
    )

    async def process_data_stream():
        status_header = st.empty()
        monitor_area = st.empty()
        status_detail = st.empty()

        if not user_id or not user_pw:
            st.error("Check credentials.")
            return

        try:
            client = _login_with_retry(user_id, user_pw)
            status_header.info("KORAIL connection established.")
        except Exception as e:
            st.error(f"Connection Failed: {e}")
            return

        tg_token = bot_token if noti_ready else ""
        tg_chat_id = chat_id if noti_ready else ""

        if noti_ready:
            start_msg = (
                f"📡 KTX Monitor Started\n"
                f"👤 User: {user_id}\n"
                f"🛤 Route: [{src_node} -> {dst_node}]\n"
                f"🕒 Window: {date_str} {start_hhmm}~{end_hhmm}"
            )
            await _send_telegram(tg_token, tg_chat_id, start_msg)

        st.button("Stop Process (Refresh Page)")

        flag = False
        loop_count = 0
        depart_after = _build_depart_after(date_str, start_hhmm)

        status_header.success("KTX monitor active...")

        try:
            while not flag:
                loop_count += 1
                status_header.info(f"🔄 Sync Loop: #{loop_count}")

                try:
                    items = _candidate_trains(
                        client,
                        src_node,
                        dst_node,
                        depart_after,
                        end_hhmm,
                        train_type,
                        include_waiting_list,
                    )
                except NoResultsError:
                    items = []
                except PastDepartureError:
                    st.error("검색 시작 시각이 이미 지났습니다. 종료합니다.")
                    return
                except NeedToLoginError:
                    status_detail.warning("세션 만료, 재로그인 시도")
                    _safe_relogin(client, user_id, user_pw)
                    await asyncio.sleep(1)
                    continue
                except (NetFunnelError, TransportError) as e:
                    status_detail.warning(f"네트워크/대기열 오류: {e}")
                    items = []
                except KorailError as e:
                    status_detail.warning(f"검색 오류: {e}")
                    items = []
                except Exception as e:
                    status_detail.warning(f"예상치 못한 검색 오류: {type(e).__name__}: {e}")
                    items = []

                log_text = f"timestamp: {datetime.now().strftime('%H:%M:%S')} | candidates: {len(items)}\n"
                log_text += "-" * 50 + "\n"
                log_text += "   TIME   | TRAIN | STATUS\n"
                log_text += "-" * 50 + "\n"

                for item in items:
                    log_text += f" {_train_dep_time(item):>7} | {_train_number(item):^5} | AVAILABLE\n"

                if not items:
                    log_text += " (no available train in selected window)\n"

                monitor_area.code(log_text, language="yaml")

                if items:
                    status_detail.write(f"🔍 Target Detected [{_train_number(items[0])}]! Acquiring...")
                    target_train, reservation, reserve_err = _try_reserve_first(
                        client,
                        items,
                        int(adults),
                        reserve_option,
                    )

                    if reservation:
                        ref_code = _reservation_ref(reservation)
                        success_msg = (
                            f"🎉 KTX 예약 성공!\n"
                            f"👤 User: {user_id}\n"
                            f"🚆 Train: {_train_number(target_train)} ({_train_dep_time(target_train)})"
                        )
                        st.balloons()
                        st.success(success_msg)

                        sound_html = """
                        <audio autoplay>
                            <source src=\"https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg\" type=\"audio/ogg\">
                        </audio>
                        <script>
                            var count = 0;
                            var audio = document.querySelector('audio');
                            audio.addEventListener('ended', function() {
                                count++;
                                if (count < 3) { audio.play(); }
                            });
                        </script>
                        """
                        st.components.v1.html(sound_html, height=0)

                        await _send_telegram(tg_token, tg_chat_id, success_msg)
                        await _send_telegram(tg_token, tg_chat_id, f"🎫 Ref Code: {ref_code}")

                        flag = True
                        break

                    if reserve_err:
                        status_detail.warning(f"예약 실패: {reserve_err}")

                min_sec, max_sec = interval_range
                sleep_time = random.uniform(min_sec, max_sec)
                status_detail.warning(f"⏳ Idle State: {sleep_time:.1f}s")
                await asyncio.sleep(sleep_time)
        finally:
            try:
                client.close()
            except Exception:
                pass

        if flag:
            status_header.success("Process Completed.")

    if st.button("Start Sync Process", type="primary"):
        asyncio.run(process_data_stream())


# ============================================================
# 진입점 분기
# ============================================================
if _is_streamlit():
    run_streamlit()
else:
    run_cli()
