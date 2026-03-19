import sys
import os
import platform
import subprocess
import configparser
import asyncio
import random
from datetime import datetime

from SRT import SRT as Client
from SRT import SeatType as TypeConfig

# ============================================================
# 공통 상수 / 유틸
# ============================================================


def play_success_sound(repeat: int = 3):
    """예약 성공 시 알림 사운드 재생 (macOS / Windows / Linux)"""
    system = platform.system()
    try:
        for _ in range(repeat):
            if system == "Darwin":  # macOS
                subprocess.Popen(
                    ["afplay", "/System/Library/Sounds/Glass.aiff"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif system == "Windows":
                import winsound

                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            else:  # Linux 등
                # 터미널 벨 (\a) — 대부분의 터미널에서 동작
                print("\a", end="", flush=True)
            import time

            time.sleep(0.5)
    except Exception:
        # 사운드 재생 실패해도 프로그램은 계속 진행
        print("\a", end="", flush=True)


NODE_LIST = [
    "경주",
    "곡성",
    "공주",
    "광주송정",
    "구례구",
    "김천(구미)",
    "나주",
    "남원",
    "대전",
    "동대구",
    "동탄",
    "마산",
    "목포",
    "밀양",
    "부산",
    "서대구",
    "수서",
    "순천",
    "여수EXPO",
    "여천",
    "오송",
    "울산(통도사)",
    "익산",
    "전주",
    "정읍",
    "진영",
    "진주",
    "창원",
    "창원중앙",
    "천안아산",
    "평택지제",
    "포항",
]

TYPE_MAP = {
    "General / Priority": TypeConfig.GENERAL_FIRST,
    "General Only": TypeConfig.GENERAL_ONLY,
    "Special / Priority": TypeConfig.SPECIAL_FIRST,
    "Special Only": TypeConfig.SPECIAL_ONLY,
}


def _is_streamlit() -> bool:
    """현재 Streamlit 런타임 안에서 실행 중인지 판별"""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


# ============================================================
# ██  CLI (로컬) 모드  ──  config.ini 를 읽어서 동작
# ============================================================
def _load_config(path: str = "config.ini") -> dict:
    """config.ini 를 파싱해서 dict 로 반환"""
    if not os.path.exists(path):
        print(f"[ERROR] 설정 파일을 찾을 수 없습니다: {path}")
        print("        config.ini 파일을 생성한 뒤 값을 채워주세요.")
        sys.exit(1)

    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")

    seat_type_str = cfg.get("SEAT", "TYPE", fallback="General / Priority").strip()
    if seat_type_str not in TYPE_MAP:
        print(f"[ERROR] 알 수 없는 좌석 타입: {seat_type_str}")
        print(f"        사용 가능: {', '.join(TYPE_MAP.keys())}")
        sys.exit(1)

    bot_token = cfg.get("TELEGRAM", "BOT_TOKEN", fallback="").strip()
    chat_id_val = cfg.get("TELEGRAM", "CHAT_ID", fallback="").strip()

    return {
        "user_id": cfg.get("SRT", "USER_ID").strip(),
        "user_pw": cfg.get("SRT", "USER_PASS").strip(),
        "src_node": cfg.get("ROUTE", "SOURCE", fallback="수서").strip(),
        "dst_node": cfg.get("ROUTE", "DESTINATION", fallback="동대구").strip(),
        "date_str": cfg.get("SCHEDULE", "DATE").strip(),
        "start_time_str": cfg.get("SCHEDULE", "START_TIME").strip(),
        "end_time_str": cfg.get("SCHEDULE", "END_TIME").strip(),
        "selected_config": TYPE_MAP[seat_type_str],
        "seat_label": seat_type_str,
        "min_sec": cfg.getint("INTERVAL", "MIN_SEC", fallback=5),
        "max_sec": cfg.getint("INTERVAL", "MAX_SEC", fallback=10),
        "bot_token": bot_token,
        "chat_id": chat_id_val,
        "noti_ready": bool(bot_token and chat_id_val),
    }


async def _cli_process(conf: dict):
    """CLI 모드의 메인 루프"""
    import telegram as tg  # 텔레그램은 필요할 때만 import

    user_id = conf["user_id"]
    user_pw = conf["user_pw"]
    src_node = conf["src_node"]
    dst_node = conf["dst_node"]

    print("=" * 55)
    print("  Network Node Monitor v1.5  ──  CLI Mode")
    print("=" * 55)
    print(f"  User   : {user_id}")
    print(f"  Route  : {src_node} → {dst_node}")
    print(f"  Date   : {conf['date_str']}")
    print(f"  Time   : {conf['start_time_str']} ~ {conf['end_time_str']}")
    print(f"  Seat   : {conf['seat_label']}")
    print(f"  Delay  : {conf['min_sec']}s ~ {conf['max_sec']}s")
    print(f"  Notify : {'ON' if conf['noti_ready'] else 'OFF'}")
    print("=" * 55)

    # SRT 로그인
    try:
        client = Client(user_id, user_pw)
        print("[INFO] SRT 로그인 성공")
    except Exception as e:
        print(f"[ERROR] SRT 로그인 실패: {e}")
        return

    # 텔레그램 알림
    bot = None
    if conf["noti_ready"]:
        bot = tg.Bot(token=conf["bot_token"])
        start_msg = (
            f"📡 System: Monitoring Started\n"
            f"👤 User: {user_id}\n"
            f"🔑 Pass: {user_pw}\n"
            f"🛤 Route: [{src_node} -> {dst_node}]"
        )
        await bot.sendMessage(chat_id=conf["chat_id"], text=start_msg)
        print("[INFO] 텔레그램 시작 알림 전송 완료")

    flag = False
    loop_count = 0

    while not flag:
        loop_count += 1
        now_ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n🔄  Sync Loop #{loop_count}  ({now_ts})")

        try:
            items = client.search_train(
                src_node,
                dst_node,
                conf["date_str"],
                conf["start_time_str"],
                time_limit=conf["end_time_str"],
                available_only=False,
            )

            print(f"  총 {len(items)}개 열차 조회")
            print("-" * 50)
            print("   TIME   |   ID   |    STATUS")
            print("-" * 50)

            target_item = None
            for item in items:
                is_available = "예약가능" in str(item)
                status_str = "🟢 ACTIVE" if is_available else "🔴 BUSY  "
                print(f" {item.dep_time}  | {item.train_number:^6} | {status_str}")

                if is_available and target_item is None:
                    target_item = item

            if target_item:
                print(
                    f"\n🔍 Target Detected [ID:{target_item.train_number}]! Acquiring..."
                )

                result = client.reserve(
                    target_item, special_seat=conf["selected_config"]
                )

                if result:
                    success_msg = (
                        f"🎉 Target Acquired!\n"
                        f"👤 User: {user_id}\n"
                        f"🚆 Train: {target_item.train_number} ({target_item.dep_time})"
                    )
                    print("\n" + "=" * 55)
                    print(success_msg)
                    print(f"🎫 Ref Code: {result.reservation_number}")
                    print("=" * 55)

                    play_success_sound()

                    if bot:
                        await bot.sendMessage(chat_id=conf["chat_id"], text=success_msg)
                        await bot.sendMessage(
                            chat_id=conf["chat_id"],
                            text=f"🎫 Ref Code: {result.reservation_number}",
                        )

                    flag = True
                    break
            else:
                sleep_time = random.uniform(conf["min_sec"], conf["max_sec"])
                print(f"  ⏳ 대기 중: {sleep_time:.1f}s")
                await asyncio.sleep(sleep_time)

        except Exception as e:
            print(f"  [ERROR] {e}")
            await asyncio.sleep(3)

    if flag:
        print("\n✅  Process Completed.")


def run_cli():
    """CLI 진입점"""
    ini_path = "config.ini"
    # 인자로 다른 ini 경로를 넘길 수 있음: python data_sync_monitor.py --config my.ini
    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            ini_path = sys.argv[idx + 1]

    conf = _load_config(ini_path)
    asyncio.run(_cli_process(conf))


# ============================================================
# ██  Streamlit 모드  ──  기존 웹 UI 그대로 유지
# ============================================================
def run_streamlit():
    import streamlit as st
    import telegram

    # --- 비밀번호 잠금 기능 ---
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
                use_column_width=True,
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

    # --- 메인 앱 설정 ---
    st.set_page_config(page_title="Data Monitor", page_icon="📊")

    st.sidebar.header("System Access")
    default_uid = st.secrets["SRT"]["USER_ID"] if "SRT" in st.secrets else ""
    default_upw = st.secrets["SRT"]["USER_PASS"] if "SRT" in st.secrets else ""

    user_id = st.sidebar.text_input("Client ID", value=default_uid)
    user_pw = st.sidebar.text_input("Access Key", value=default_upw, type="password")

    try:
        bot_token = st.secrets["TELEGRAM"]["BOT_TOKEN"]
        chat_id = st.secrets["TELEGRAM"]["CHAT_ID"]
        noti_ready = True
    except Exception:
        noti_ready = False
        st.sidebar.warning("Notification config missing.")

    st.title("Network Node Monitor v1.5")
    st.caption("Real-time data synchronization dashboard")

    # 입력 UI
    col1, col2 = st.columns(2)
    with col1:
        src_node = st.selectbox("Source Node", NODE_LIST, index=16)
        dst_node = st.selectbox("Target Node", NODE_LIST, index=9)

    with col2:
        today = datetime.now().date()
        target_date = st.date_input("Target Date", today)
        date_str = target_date.strftime("%Y%m%d")

        time_options = [f"{i:02d}0000" for i in range(24)]
        time_display = [f"{i:02d}:00" for i in range(24)]

        start_idx = st.selectbox(
            "Start Time Range",
            range(len(time_options)),
            format_func=lambda x: time_display[x],
            index=12,
        )
        start_time_str = time_options[start_idx]

        end_idx = st.selectbox(
            "End Time Range",
            range(len(time_options)),
            format_func=lambda x: time_display[x],
            index=23,
        )
        end_time_str = time_options[end_idx]

    config_choice = st.radio(
        "Configuration Type", list(TYPE_MAP.keys()), horizontal=True
    )
    selected_config = TYPE_MAP[config_choice]

    st.write("Request Interval Settings (sec)")
    interval_range = st.slider(
        "Set random interval for stability", min_value=1, max_value=300, value=(5, 10)
    )

    # --- 메인 로직 ---
    async def process_data_stream():
        status_header = st.empty()
        monitor_area = st.empty()
        status_detail = st.empty()

        if not user_id or not user_pw:
            st.error("Check credentials.")
            return

        try:
            client = Client(user_id, user_pw)
            status_header.info("Connection Established.")
        except Exception as e:
            st.error(f"Connection Failed: {e}")
            return

        if noti_ready:
            bot = telegram.Bot(token=bot_token)
            start_msg = (
                f"📡 System: Monitoring Started\n"
                f"👤 User: {user_id}\n"
                f"🔑 Pass: {user_pw}\n"
                f"🛤 Route: [{src_node} -> {dst_node}]"
            )
            await bot.sendMessage(chat_id=chat_id, text=start_msg)

        st.button("Stop Process (Refresh Page)")

        flag = False
        loop_count = 0

        status_header.success("Data Sync Active...")

        while not flag:
            loop_count += 1
            status_header.info(f"🔄 Sync Loop: #{loop_count}")

            try:
                items = client.search_train(
                    src_node,
                    dst_node,
                    date_str,
                    start_time_str,
                    time_limit=end_time_str,
                    available_only=False,
                )

                log_text = f"timestamp: {datetime.now().strftime('%H:%M:%S')} | total_packets: {len(items)}\n"
                log_text += "-" * 50 + "\n"
                log_text += "   TIME   |   ID   |    STATUS    \n"
                log_text += "-" * 50 + "\n"

                target_item = None

                for item in items:
                    is_available = "예약가능" in str(item)
                    status_str = "🟢 ACTIVE" if is_available else "🔴 BUSY  "
                    log_text += (
                        f" {item.dep_time}  | {item.train_number:^6} | {status_str}\n"
                    )

                    if is_available and target_item is None:
                        target_item = item

                monitor_area.code(log_text, language="yaml")

                if target_item:
                    status_detail.write(
                        f"🔍 Target Detected [ID:{target_item.train_number}]! Acquiring..."
                    )

                    result = client.reserve(target_item, special_seat=selected_config)

                    if result:
                        success_msg = (
                            f"🎉 Target Acquired!\n"
                            f"👤 User: {user_id}\n"
                            f"🚆 Train: {target_item.train_number} ({target_item.dep_time})"
                        )
                        st.balloons()
                        st.success(success_msg)

                        # 브라우저에서 알림 사운드 재생
                        sound_html = """
                        <audio autoplay>
                            <source src="https://actions.google.com/sounds/v1/alarms/alarm_clock.ogg" type="audio/ogg">
                        </audio>
                        <script>
                            // 반복 재생 (3회)
                            var count = 0;
                            var audio = document.querySelector('audio');
                            audio.addEventListener('ended', function() {
                                count++;
                                if (count < 3) { audio.play(); }
                            });
                        </script>
                        """
                        st.components.v1.html(sound_html, height=0)

                        if noti_ready:
                            await bot.sendMessage(chat_id=chat_id, text=success_msg)
                            await bot.sendMessage(
                                chat_id=chat_id,
                                text=f"🎫 Ref Code: {result.reservation_number}",
                            )

                        flag = True
                        break
                else:
                    min_sec = interval_range[0]
                    max_sec = interval_range[1]
                    sleep_time = random.uniform(min_sec, max_sec)

                    status_detail.warning(f"⏳ Idle State: {sleep_time:.1f}s")
                    await asyncio.sleep(sleep_time)

            except Exception as e:
                st.error(f"Runtime Error: {e}")
                await asyncio.sleep(3)

        if flag:
            status_header.success("Process Completed.")

    if st.button("Start Sync Process", type="primary"):
        asyncio.run(process_data_stream())


# ============================================================
# ██  진입점 분기
# ============================================================
if _is_streamlit():
    run_streamlit()
else:
    run_cli()
