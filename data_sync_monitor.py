import streamlit as st
from SRT import SRT as Client
from SRT import SeatType as TypeConfig
import telegram
import asyncio
import random
from datetime import datetime

# --- 비밀번호 잠금 기능 (st.rerun 삭제 버전) ---
if "password_correct" not in st.session_state:

    def check_password():
        if st.session_state.password_input == st.secrets["APP_PASSWORD"]:
            st.session_state.password_correct = True
            del st.session_state.password_input
        else:
            st.error("비밀번호가 틀렸습니다.")

    st.title("🔐 Access Restricted")
    st.caption("Enter access key.")
    st.text_input(
        "Access Key", type="password", on_change=check_password, key="password_input"
    )
    st.stop()

# --- 메인 앱 시작 ---
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
except:
    noti_ready = False
    st.sidebar.warning("Notification config missing.")

st.title("Network Node Monitor v1.2")
st.caption("Real-time data synchronization dashboard")

col1, col2 = st.columns(2)
with col1:
    node_list = [
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
        "울산",
        "익산",
        "정읍",
        "진영",
        "진주",
        "창원",
        "창원중앙",
        "천안아산",
        "평택지제",
        "포항",
    ]
    src_node = st.selectbox("Source Node", node_list, index=16)
    dst_node = st.selectbox("Target Node", node_list, index=9)

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

type_map = {
    "General / Priority": TypeConfig.GENERAL_FIRST,
    "General Only": TypeConfig.GENERAL_ONLY,
    "Special / Priority": TypeConfig.SPECIAL_FIRST,
    "Special Only": TypeConfig.SPECIAL_ONLY,
}
config_choice = st.radio("Configuration Type", list(type_map.keys()), horizontal=True)
selected_config = type_map[config_choice]

st.write("Request Interval Settings (sec)")
interval_range = st.slider(
    "Set random interval for stability", min_value=1, max_value=300, value=(3, 6)
)


async def process_data_stream():
    status_header = st.empty()
    status_detail = st.empty()
    log_area = (
        st.empty()
    )  # 로그를 쌓아서 보여주기 위해 empty 대신 container 쓰거나 덮어쓰기

    if not user_id or not user_pw:
        st.error("Check credentials.")
        return

    try:
        client = Client(user_id, user_pw)
        status_header.info("Connection Established.")
    except Exception as e:
        st.error(f"Connection Failed: {e}")
        return

    # 봇 알림
    if noti_ready:
        bot = telegram.Bot(token=bot_token)
        await bot.sendMessage(
            chat_id=chat_id, text=f"System: Monitoring Started [{src_node}->{dst_node}]"
        )

    st.button("Stop Process (Refresh Page)")

    flag = False
    loop_count = 0

    status_header.success("Data Sync Active...")

    while not flag:
        loop_count += 1
        status_header.info(f"🔄 Sync Loop: #{loop_count}")

        try:
            # [핵심 수정] search_train을 루프 안으로 이동 -> 매번 새로고침!
            items = client.search_train(
                src_node,
                dst_node,
                date_str,
                start_time_str,
                time_limit=end_time_str,
                available_only=False,
            )

            # 검색 결과 중 '예약가능' 상태인 것만 필터링
            target_item = None
            for item in items:
                # 위장: 화면에는 안 보이지만 내부적으로 "예약가능" 텍스트 체크
                if "예약가능" in str(item):
                    target_item = item
                    break

            # 화면 로그 갱신
            current_time = datetime.now().strftime("%H:%M:%S")

            if target_item:
                # 찾았다!
                status_detail.write(
                    f"🔍 [{current_time}] Target Detected [ID:{target_item.train_number}]! Acquiring..."
                )

                # 예약 시도
                result = client.reserve(target_item, special_seat=selected_config)

                if result:
                    success_msg = f"Target Acquired! [ID:{target_item.train_number}] {target_item.dep_time}"
                    st.balloons()
                    st.success(success_msg)

                    if noti_ready:
                        await bot.sendMessage(chat_id=chat_id, text=success_msg)
                        await bot.sendMessage(
                            chat_id=chat_id,
                            text=f"Ref Code: {result.reservation_number}",
                        )

                    flag = True
                    break
            else:
                # 못 찾음 -> 대기
                # 로그가 너무 빨리 바뀌면 안보이니까 caption으로 상태 표시
                log_area.caption(
                    f"[{current_time}] Scanned {len(items)} items. No packet available. Idle..."
                )

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
