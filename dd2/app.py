# -----------------------------
# 📌 OpenCV 환경 변수 선언
# -----------------------------
import os
import sys

os.environ["OPENCV_VIDEOIO_PRIORITY_MSMF"] = "0"
os.environ["OPENCV_VIDEOIO_LOG_LEVEL"] = "0"
os.environ["OPENCV_LOG_LEVEL"] = "OFF"

# -----------------------------
# 필수 라이브러리 로드
# -----------------------------
import pandas as pd
import streamlit as st
import requests
import pymysql  
import time
import threading

st.set_page_config(page_title="지능형 야생동물 관제 대시보드", layout="wide")

FILTER_FILE = "filter_setting.txt"
JETSON_WIFI_IP = "220.69.20.133" 

DB_CONFIG = {
    "host": "earth.gwangju.ac.kr",
    "user": "dbuser211702",
    "password": "ce1234",
    "database": "db211702",
    "charset": "utf8mb4"
}

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1499229154674212986/gTOlgwFOAcQJ6sRFQKNOuc7hmBVAdzvtKv5AXGGKou-QAfaYBadnqWNiNUNf8_rEwH82"
TELEGRAM_TOKEN = "8967179347:AAFw3266fkoZ8j_9x0G4FYqvRx0Uyes9f6E"
TELEGRAM_CHAT_ID = "8625977853"

filter_options = {
    "🧍 사람 (테스트용)": "person",
    "📱 핸드폰 (테스트용)": "cell_phone",
    "🐗 멧돼지": "wild_boar",
    "🦌 고라니": "water_deer",
    "🦝 너구리": "raccoon_dog",
    "🐺 들개": "wild_dog"
}

def send_filter_update_async(selected_codes):
    try:
        requests.post("http://127.0.0.1:5000/set_filter", json={"filter_codes": selected_codes}, timeout=0.5)
    except:
        pass

# 💡 [추가됨] Zero-DCE 상태를 Flask 서버로 전송하는 비동기 함수
def send_dce_update_async(dce_state):
    try:
        requests.post("http://127.0.0.1:5000/toggle_dce", json={"dce_on": dce_state}, timeout=0.5)
    except:
        pass

def get_db_connection():
    try:
        return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    except Exception:
        return None

def fetch_latest_status():
    conn = get_db_connection()
    default_status = {"object_type": "없음", "confidence": "0%", "event_time": "-", "siren": "N", "light": "N", "raw_confidence": 0, "seconds_ago": 9999}
    if not conn: return default_status
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT object_type, confidence, event_time, siren_status, light_status,
                       TIMESTAMPDIFF(SECOND, event_time, NOW()) as seconds_ago
                FROM detection_logs 
                ORDER BY event_time DESC LIMIT 1
            """
            cursor.execute(sql)
            res = cursor.fetchone()
            if res:
                return {
                    "object_type": res["object_type"],
                    "confidence": f"{res['confidence'] * 100:.1f}%" if res["confidence"] else "0%",
                    "event_time": res["event_time"].strftime("%Y-%m-%d %H:%M:%S") if res["event_time"] else "-",
                    "siren": res["siren_status"],
                    "light": res["light_status"],
                    "raw_confidence": res["confidence"] if res["confidence"] else 0,
                    "seconds_ago": res["seconds_ago"] if res["seconds_ago"] is not None else 9999
                }
    except Exception: pass
    finally:
        if conn: conn.close()
    return default_status

def fetch_event_logs():
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame(columns=["발생 시간", "탐지 종류", "신뢰도", "사이렌", "경광등", "알림 상태", "캡처 사진", "특이사항"])
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT 
                    event_time as "발생 시간", 
                    object_type as "탐지 종류", 
                    CONCAT(ROUND(confidence * 100, 1), '%') as "신뢰도", 
                    IF(siren_status='Y', '🚨 ON', 'OFF') as "사이렌", 
                    IF(light_status='Y', '💡 ON', 'OFF') as "경광등", 
                    alert_status as "알림 상태",
                    image_path as "캡처 사진",
                    remarks as "특이사항"
                FROM detection_logs 
                ORDER BY event_time DESC 
                LIMIT 30
            """
            cursor.execute(sql)
            res = cursor.fetchall()
            df = pd.DataFrame(res)
            if not df.empty and "발생 시간" in df.columns:
                df['발생 시간'] = pd.to_datetime(df['발생 시간']).dt.strftime('%Y-%m-%d %H:%M:%S')
            return df
    except Exception:
        return pd.DataFrame(columns=["발생 시간", "탐지 종류", "신뢰도", "사이렌", "경광등", "알림 상태", "캡처 사진", "특이사항"])
    finally:
        if conn: conn.close()

def send_discord(msg):
    if not DISCORD_WEBHOOK_URL or "YOUR_WEBHOOK" in DISCORD_WEBHOOK_URL: return False
    try: return requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=1).status_code == 204
    except: return False

def send_telegram(msg):
    if not TELEGRAM_TOKEN or "여기에" in TELEGRAM_TOKEN: return False
    try: return requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=1).status_code == 200
    except: return False

def load_filter_setting():
    if not os.path.exists(FILTER_FILE): 
        return ["wild_boar", "water_deer", "raccoon_dog", "wild_dog"]
    with open(FILTER_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()
        return content.split(",") if content else []

def on_filter_change():
    selected_labels = st.session_state["filter_ms_key"]
    selected_codes = [filter_options[label] for label in selected_labels]
    
    st.session_state["active_filters"] = selected_codes
    
    with open(FILTER_FILE, "w", encoding="utf-8") as f:
        f.write(",".join(selected_codes))
    
    threading.Thread(target=send_filter_update_async, args=(selected_codes,), daemon=True).start()

# 💡 [추가됨] 스위치가 눌렸을 때 실행될 콜백 함수
def on_dce_change():
    dce_state = st.session_state["dce_switch_key"]
    threading.Thread(target=send_dce_update_async, args=(dce_state,), daemon=True).start()

if "active_filters" not in st.session_state:
    st.session_state["active_filters"] = load_filter_setting()
    
if "filter_ms_key" not in st.session_state:
    st.session_state["filter_ms_key"] = [k for k, v in filter_options.items() if v in st.session_state["active_filters"]]

# -----------------------------
# 📌 사이드바
# -----------------------------
st.sidebar.title("🔧 관제 제어 센터")
st.sidebar.subheader("🎯 실시간 집중 탐지 대상")

st.sidebar.multiselect(
    "감시할 대상을 선택하세요:",
    options=list(filter_options.keys()),
    key="filter_ms_key",
    on_change=on_filter_change
)

st.sidebar.divider()
st.sidebar.subheader("🔔 시스템 알림 마스터")
alert_master_switch = st.sidebar.toggle("실시간 자동 알림 발송", value=True)

# 💡 [추가됨] 야간 투시 모드 스위치 UI 
st.sidebar.divider()
st.sidebar.subheader("🌙 특수 영상 처리 엔진")
st.sidebar.toggle(
    "야간 투시 모드 (Zero-DCE) 가동", 
    value=False, 
    key="dce_switch_key", 
    on_change=on_dce_change,
    help="저조도 환경(야간)에서 딥러닝 기반 이미지 강화 알고리즘을 활성화합니다."
)

st.sidebar.divider()
selected_cameras = st.sidebar.multiselect(
    "모니터링 카메라 채널 선택", 
    ["CCTV 1 (메인 AI 카메라)", "CCTV 2 (서브 카메라)", "CCTV 3 (외곽 카메라)"], 
    default=["CCTV 1 (메인 AI 카메라)", "CCTV 2 (서브 카메라)"]
)

# -----------------------------
# 📌 메인 화면 1층 - 라이브 카메라 
# -----------------------------
st.title("🛡️ 지능형 야생동물 예찰·감시 통합 관제 시스템")
st.subheader("🖥️ 메인 실시간 관제 멀티뷰 모니터")

if not selected_cameras:
    st.warning("⚠️ 모니터링할 카메라 소스를 선택해 주세요.")
else:
    num_cams = len(selected_cameras)
    cam_cols = st.columns([1, 2]) if num_cams == 1 else st.columns(num_cams)
    
    for i, cam_name in enumerate(selected_cameras):
        target_col = cam_cols[0] if num_cams == 1 else cam_cols[i]
        
        with target_col:
            with st.container(border=True):
                st.markdown(f"**● LIVE - {cam_name}**")
                cam_width = st.slider(f"🔍 크기 조절 ({cam_name})", min_value=200, max_value=1000, value=400, step=50, key=f"slider_{cam_name}")
                
                if "CCTV 1" in cam_name:
                    st.markdown(f'<img src="http://{JETSON_WIFI_IP}:5000/video_feed/CAM_01" width="{cam_width}px">', unsafe_allow_html=True)
                elif "CCTV 2" in cam_name:
                    st.markdown(f'<img src="http://{JETSON_WIFI_IP}:5000/video_feed/CAM_02" width="{cam_width}px">', unsafe_allow_html=True)
                else:
                    st.image("https://images.unsplash.com/photo-1541888946425-d81bb19240f5?q=80&w=800&auto=format&fit=crop", width=cam_width)

st.divider()

# -----------------------------
# 🔄 메인 화면 2~3층 - 동적 데이터 영역 (프래그먼트)
# -----------------------------
@st.fragment(run_every=3)
def auto_refresh_data():
    db_data = fetch_latest_status()
    log_df = fetch_event_logs()
    is_recent_event = db_data["seconds_ago"] < 60

    if alert_master_switch and is_recent_event and db_data["object_type"] != "없음":
        if "last_alert_time" not in st.session_state or st.session_state["last_alert_time"] != db_data["event_time"]:
            alert_msg = f"🚨 [위험 감지] {db_data['event_time']}에 {db_data['object_type']}(신뢰도: {db_data['confidence']})가 감지되었습니다!"
            threading.Thread(target=send_discord, args=(alert_msg,), daemon=True).start()
            threading.Thread(target=send_telegram, args=(alert_msg,), daemon=True).start()
            st.session_state["last_alert_time"] = db_data["event_time"]

    with st.container():
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("활성 감시 타겟", f"{len(st.session_state['active_filters'])}종 감시 중")
        col2.metric("최근 탐지 동물", db_data["object_type"])
        col3.metric("AI 탐지 신뢰도", db_data["confidence"])
        col4.metric("최근 감지 시각", db_data["event_time"])
        
        st.divider()

        left_data, right_data = st.columns([1, 1])

        with left_data:
            st.subheader("⚠️ 실시간 감시 시나리오")
            is_trespassing = db_data["object_type"] != "없음"
            status = "🔴 위험 (발생!)" if (is_trespassing and is_recent_event) else "🟢 정상 (대기중)"
            
            with st.container(border=True):
                st.markdown("**🚨 무단 침입 감지**")
                st.markdown(f"### {status}")
                st.caption(f"최근 탐지 신뢰도: {db_data['confidence']}" if (is_trespassing and is_recent_event) else "탐지 대기 중...")

        with right_data:
            st.subheader("🚨 하드웨어 경보 및 원격 제어 상태")
            device_state = {
                "LED 경광등": "ON 🔴" if (is_recent_event and db_data["light"] == "Y") else "OFF ⚪",
                "사이렌": "ON 🔴" if (is_recent_event and db_data["siren"] == "Y") else "OFF ⚪",
                "스피커 방송": "ON 🔴" if (is_recent_event and db_data["siren"] == "Y") else "OFF ⚪",
                "디스코드/텔레그램": "실시간 대기 🟢" if alert_master_switch else "알림 차단 (OFF) 🔴"
            }
            st.dataframe(pd.DataFrame([{"시스템 연동 제어 항목": k, "현재 물리 출력 상태": v} for k, v in device_state.items()]), width="stretch", hide_index=True)

        st.divider()
        st.subheader("📋 전체 통합 이벤트 로그 / 야생동물 관제 이력")
        
        if not log_df.empty:
            st.dataframe(
                log_df, width="stretch", hide_index=True,
                column_config={
                    "특이사항": st.column_config.TextColumn("특이사항", width="medium"),
                    "캡처 사진": st.column_config.LinkColumn("캡처 사진", display_text="📸 확인하기")
                },
                use_container_width=True
            )
        else:
            st.info("기록된 데이터베이스 야생동물 이력이 아직 없습니다.")

        st.logo("https://img.icons8.com/color/48/shield.png")
        st.caption("🔒 지능형 야생동물 보안 코어 엔진 작동 중")

auto_refresh_data()
