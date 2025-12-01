import streamlit as st
from SRT import SRT as Client
from SRT import SeatType as TypeConfig
import telegram
import asyncio
import random
from datetime import datetime

if "password_correct" not in st.session_state:
    
    def check_password():
        # Secrets에 저장된 앱 비밀번호와 사용자가 입력한 값 비교
        if st.session_state.password_input == st.secrets["APP_PASSWORD"]:
            st.session_state.password_correct = True
            del st.session_state.password_input  # 비밀번호는 세션에 남기지 않음
            st.experimental_rerun()
        else:
            st.error("비밀번호가 틀렸습니다. 지인에게 문의하세요.")

    st.title("🔐 Access Restricted")
    st.caption("Please enter the shared access key to continue.")
    
    st.text_input(
        "Access Key",
        type="password",
        on_change=check_password,
        key="password_input"
    )
    
    st.stop() # 이 명령어 아래의 모든 코드는 실행되지 않습니다.
    
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

st.title("Network Node Monitor v1.0")
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
    "Set random interval for stability", min_value=1, max_value=300, value=(30, 60)
)


async def process_data_stream():
    status_header = st.empty()
    status_detail = st.empty()
    log_area = st.empty()

    if not user_id or not user_pw:
        st.error("Access denied. Please check credentials.")
        return

    try:
        client = Client(user_id, user_pw)
        status_header.info("Connection Established. Scanning packets...")
    except Exception as e:
        st.error(f"Connection Failed: {e}")
        return

    try:
        items = client.search_train(
            src_node,
            dst_node,
            date_str,
            start_time_str,
            time_limit=end_time_str,
            available_only=False,
        )

        st.write(f"Monitor Range: {time_display[start_idx]} ~ {time_display[end_idx]}")
        st.write(f"Detected Items: {len(items)}")

        item_list_text = ""
        for item in items:
            item_list_text += (
                f"[ID:{item.train_number}] {item.dep_time}~{item.arr_time}\n"
            )

        if not items:
            st.warning("No data found in this range.")
            return

        with st.expander("Show Data List"):
            st.text(item_list_text)

        if noti_ready:
            bot = telegram.Bot(token=bot_token)
            await bot.sendMessage(
                chat_id=chat_id,
                text=f"System: Monitoring Started [{src_node}->{dst_node}] ({len(items)} items)",
            )

        st.button("Stop Process (Refresh Page)")

        flag = False
        loop_count = 0

        status_header.success("Data Sync Active...")

        while not flag:
            loop_count += 1
            status_header.info(f"🔄 Sync Loop: #{loop_count}")

            for item in items:
                try:
                    min_sec = interval_range[0]
                    max_sec = interval_range[1]
                    sleep_time = random.uniform(min_sec, max_sec)

                    status_detail.warning(f"⏳ Idle State: {sleep_time:.1f}s")

                    await asyncio.sleep(sleep_time)

                    status_detail.write(
                        f"🔍 Verifying Item [ID:{item.train_number}] {item.dep_time}..."
                    )

                    result = client.reserve(item, special_seat=selected_config)

                    if result:
                        success_msg = (
                            f"Target Acquired! [ID:{item.train_number}] {item.dep_time}"
                        )
                        st.balloons()
                        st.success(success_msg)
                        status_detail.success("Process Completed Successfully.")

                        if noti_ready:
                            await bot.sendMessage(chat_id=chat_id, text=success_msg)
                            await bot.sendMessage(
                                chat_id=chat_id,
                                text=f"Ref Code: {result.reservation_number}",
                            )

                        flag = True
                        break

                except ValueError:
                    log_area.caption(
                        f"[{datetime.now().strftime('%H:%M:%S')}] Item {item.dep_time} : Data Unavailable"
                    )
                    pass
                except Exception as e:
                    st.error(f"Runtime Error: {e}")

            if flag:
                break

    except Exception as e:
        st.error(f"System Error: {e}")


if st.button("Start Sync Process", type="primary"):
    asyncio.run(process_data_stream())
