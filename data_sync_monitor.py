import streamlit as st
from SRT import SRT as Client
from SRT import SeatType as TypeConfig
import telegram
import asyncio
import random
from datetime import datetime

# --- 비밀번호 잠금 기능 ---
if "password_correct" not in st.session_state:

    def check_password():
        if st.session_state.password_input == st.secrets["APP_PASSWORD"]:
            st.session_state.password_correct = True
            del st.session_state.password_input
        else:
            st.error("비밀번호가 틀렸습니다. 다시 시도해주세요.")

    # 1. 화면 중앙 정렬을 위한 컬럼 나누기 (선택 사항)
    col1, col2, col3 = st.columns([1, 4, 1])

    with col2:
        # 여기에 원하는 이미지 주소를 넣으세요!
        # 예시: 귀여운 앵무새 이미지 (인터넷 링크)
        # 만약 깃허브에 올린 파일이라면 "image.jpg" 처럼 파일명만 쓰면 됩니다.
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
except:
    noti_ready = False
    st.sidebar.warning("Notification config missing.")

st.title("Network Node Monitor v1.5")
st.caption("Real-time data synchronization dashboard")

# 입력 UI
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
        "울산(통도사)",
        "익산",
        '전주',
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
