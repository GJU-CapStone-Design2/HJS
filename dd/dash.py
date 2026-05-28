# -----------------------------
# 📌 [경고 차단] OpenCV 로드 전 환경 변수 우선 선언 (순서 절대 변경 금지)
# -----------------------------
import os
import sys

os.environ["OPENCV_VIDEOIO_PRIORITY_MSMF"] = "0"
os.environ["OPENCV_VIDEOIO_LOG_LEVEL"] = "0"
os.environ["OPENCV_LOG_LEVEL"] = "OFF"

# -----------------------------
# 필수 라이브러리 로드
# -----------------------------
import datetime
import pandas as pd
import streamlit as st
import requests
import cv2  
import numpy as np
import pymysql  
import time

# 대시보드를 브라우저 가로 끝까지 꽉 차게 설정
st.set_page_config(page_title="지능형 야생동물 관제 대시보드", layout="wide")

# -----------------------------
# 📌 [성진님 연동 설정] 일체형 및 스마트폰 다중 관제용 IP 설정
# -----------------------------
# 젯슨 내부 모니터로만 볼 때는 "localhost"로 두셔도 됩니다.
# 단, 스마트폰을 와이파이로 연결해 동시 시연할 때는 젯슨의 실제 와이파이 IP(예: "192.168.0.15")를 입력하세요!
JETSON_WIFI_IP = "220.69.20.133" 

# -----------------------------
# [필수 설정] 🛠️ 광주대학교 외부 DB 서버 연동 정보 반영 완료
# -----------------------------
DB_CONFIG = {
    "host": "earth.gwangju.ac.kr",       # 👈 지정해주신 학교 DB 서버 주소
    "user": "dbuser211702",             # 👈 사용자 계정
    "password": "ce1234",               # 👈 비밀번호
    "database": "db211702",             # 👈 디비 이름
    "charset": "utf8mb4"
}

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1499229154674212986/gTOlgwFOAcQJ6sRFQKNOuc7hmBVAdzvtKv5AXGGKou-QAfaYBadnqWNiNUNf8_rEwH82"
TELEGRAM_TOKEN = "8967179347:AAFw3266fkoZ8j_9x0G4FYqvRx0Uyes9f6E"
TELEGRAM_CHAT_ID = "8625977853"

# -----------------------------
# 데이터베이스 연동 함수 정의
# -----------------------------
def get_db_connection():
    try:
        return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    except Exception as e:
        st.error(f"❌ 데이터베이스 연결 실패 (earth.gwangju.ac.kr): {e}")
        return None

def fetch_latest_status():
    conn = get_db_connection()
    default_status = {"object_type": "없음", "confidence": "0%", "event_time": "-", "siren": "N", "light": "N", "raw_confidence": 0}
    if not conn: return default_status
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT object_type, confidence, event_time, siren_status, light_status FROM detection_logs ORDER BY event_time DESC LIMIT 1")
            res = cursor.fetchone()
            if res:
                return {
                    "object_type": res["object_type"],
                    "confidence": f"{res['confidence'] * 100:.1f}%" if res["confidence"] else "0%",
                    "event_time": res["event_time"].strftime("%Y-%m-%d %H:%M:%S") if res["event_time"] else "-",
                    "siren": res["siren_status"],
                    "light": res["light_status"],
                    "raw_confidence": res["confidence"] if res["confidence"] else 0
                }
    except Exception: pass
    finally:
        if conn: conn.close()
    return default_status

def fetch_event_logs():
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame(columns=["발생 시간", "탐지 종류", "신뢰도", "사이렌", "경광등", "알림 상태", "특이사항"])
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT 
                    DATE_FORMAT(event_time, '%%Y-%%m-%%d %%H:%%i:%%s') as "발생 시간", 
                    object_type as "탐지 종류", 
                    CONCAT(ROUND(confidence * 100, 1), '%%') as "신뢰도", 
                    IF(siren_status='Y', '🚨 ON', 'OFF') as "사이렌", 
                    IF(light_status='Y', '💡 ON', 'OFF') as "경광등", 
                    alert_status as "알림 상태",
                    remarks as "특이사항"
                FROM detection_logs 
                ORDER BY event_time DESC 
                LIMIT 30
            """
            cursor.execute(sql)
            res = cursor.fetchall()
            if res: return pd.DataFrame(res)
    except Exception: pass
    finally:
        if conn: conn.close()
    return pd.DataFrame(columns=["발생 시간", "탐지 종류", "신뢰도", "사이렌", "경광등", "알림 상태", "특이사항"])

# 📌 [수정됨] 파일 기반에서 젯슨 메인 시스템(YOLO) 직접 API 제어 방식으로 변경
def save_filter_setting(animal_code):
    try:
        # 대시보드가 구동되는 로컬 호스트 내부의 5000번 포트(메인 시스템)로 필터 코드 직접 송신
        requests.post("http://127.0.0.1:5000/set_filter", json={"filter_code": animal_code}, timeout=1)
    except Exception:
        pass

def load_filter_setting():
    # 새로고침 시 UI 풀림 방지를 위해 스트림릿 내부 메모리(Session State) 기반으로 변경
    if "current_filter" not in st.session_state:
        st.session_state["current_filter"] = "all"
    return st.session_state["current_filter"]

# 메신저 알림 함수
def send_discord(msg):
    if not DISCORD_WEBHOOK_URL or "YOUR_WEBHOOK" in DISCORD_WEBHOOK_URL: return False
    try: return requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=2).status_code == 204
    except: return False

def send_telegram(msg):
    if not TELEGRAM_TOKEN or "여기에" in TELEGRAM_TOKEN: return False
    try: return requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=2).status_code == 200
    except: return False

# -----------------------------
# 데이터 실시간 로드 및 상태 매핑
# -----------------------------
db_data = fetch_latest_status()
log_df = fetch_event_logs()
current_filter = load_filter_setting()

device_state = {
    "LED 경광등": "ON" if db_data["light"] == "Y" else "OFF",
    "사이렌": "ON" if db_data["siren"] == "Y" else "OFF",
    "스피커 방송": "ON" if db_data["siren"] == "Y" else "OFF",
    "디스코드/텔레그램": "실시간 대기"
}

# -----------------------------
# 사이드바 (제어 패널)
# -----------------------------
st.sidebar.title("🔧 관제 제어 센터")
st.sidebar.subheader("🎯 집중 탐지 대상 설정")
filter_options = {
    "전체 탐지 (ALL)": "all",
    "🐗 멧돼지 (Wild Boar)": "wild_boar",
    "🦌 고라니 (Water Deer)": "water_deer",
    "🦝 너구리 (Raccoon Dog)": "raccoon_dog",
    "🐕 들개 (Wild Dog)": "wild_dog"
}

current_index = list(filter_options.values()).index(current_filter) if current_filter in filter_options.values() else 0
selected_filter_label = st.sidebar.selectbox("카메라 감시 대상 지정:", list(filter_options.keys()), index=current_index)

chosen_code = filter_options[selected_filter_label]
if chosen_code != current_filter:
    save_filter_setting(chosen_code)
    st.session_state["current_filter"] = chosen_code  # 세션 동기화 추가
    st.sidebar.success(f"⚙️ 타겟 변경: {chosen_code}")
    time.sleep(0.3)
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("🔔 시스템 알림 마스터")
alert_master_switch = st.sidebar.toggle("실시간 자동 알림 발송", value=True)

# 📌 [복구 1] 다중 카메라 채널 멀티 선택창 복구 (2~3개 캠 대응용)
st.sidebar.divider()
selected_cameras = st.sidebar.multiselect(
    "모니터링 카메라 채널 선택", 
    ["CCTV 1 (메인 AI 카메라)", "CCTV 2 (서브 가상 스트림)", "CCTV 3 (외곽 가상 스트림)"], 
    default=["CCTV 1 (메인 AI 카메라)", "CCTV 2 (서브 가상 스트림)"]
)

st.sidebar.divider()
st.sidebar.subheader("📢 알림 수동 테스트")
if st.sidebar.button("🚀 디스코드 테스트 알림"):
    send_discord("🔔 [테스트] 원격 대시보드 알리미 정상 가동")
if st.sidebar.button("✈️ 텔레그램 테스트 알림"):
    send_telegram("🔔 [테스트] 원격 대시보드 알리미 정상 가동")

# 자동 알림 전송 연산
if alert_master_switch and db_data["object_type"] != "없음" and db_data["raw_confidence"] > 0.7:
    if "last_alert_time" not in st.session_state or st.session_state["last_alert_time"] != db_data["event_time"]:
        alert_msg = f"🚨 [위험 감지] {db_data['event_time']}에 {db_data['object_type']}(신뢰도: {db_data['confidence']})가 감지되었습니다!"
        send_discord(alert_msg)
        send_telegram(alert_msg)
        st.session_state["last_alert_time"] = db_data["event_time"]

# -----------------------------
# 메인 통합 대시보드 화면 구성
# -----------------------------
st.title("🛡️ 지능형 야생동물 예찰·감시 통합 관제 시스템")

col1, col2, col3, col4 = st.columns(4)
col1.metric("필터링 타겟", selected_filter_label.split(" ")[1] if " " in selected_filter_label else "전체")
col2.metric("최근 탐지 동물", db_data["object_type"])
col3.metric("AI 탐지 신뢰도", db_data["confidence"])
col4.metric("최근 감지 시각", db_data["event_time"])

st.divider()

# -----------------------------
# 1층: 메인 실시간 관제 모니터 (멀티뷰 & 확대/축소 완벽 복구)
# -----------------------------
st.subheader("🖥️ 메인 실시간 관제 멀티뷰 모니터")

if not selected_cameras:
    st.warning("⚠️ 모니터링할 카메라 소스를 선택해 주세요.")
else:
    # 📌 [수정됨] 카메라 충돌을 완전히 방지하기 위해 VideoCapture(0) 장치를 직접 열지 않고,
    # 메인 엔진(Flask)이 실시간 송출 중인 영상 주소(MJPEG Stream)를 원격 클라이언트 형태로 받아옵니다.
    VIRTUAL_STREAM_URL = "https://images.unsplash.com/photo-1541888946425-d81bb19240f5?q=80&w=800&auto=format&fit=crop"

    # 선택된 카메라 개수에 따라 유연하게 분할 화면 레이아웃 생성 (2~3단 자동 구성)
    num_cams = len(selected_cameras)
    cam_cols = st.columns([1, 2]) if num_cams == 1 else st.columns(num_cams)
    
    for i, cam_name in enumerate(selected_cameras):
        target_col = cam_cols[0] if num_cams == 1 else cam_cols[i]
        with target_col:
            with st.container(border=True):
                st.markdown(f"**● LIVE - {cam_name}**")
                
                # 📌 [복구 2] 각 캠 마다 독립 작동하는 개별 확대/축소(크기 조절) 슬라이더 복구
                cam_width = st.slider(
                    f"🔍 크기 조절 ({cam_name})", 
                    min_value=200, max_value=1000, value=400, step=50, 
                    key=f"slider_{cam_name}"
                )
                
                # 📌 [수정됨] 선택한 채널명에 매핑되는 메인 서버의 영상 스트리밍 라우트를 매칭하여 렌더링합니다.
                if "CCTV 1" in cam_name:
                    st.markdown(f'<img src="http://{JETSON_WIFI_IP}:5000/video_feed/CAM_01" width="{cam_width}px">', unsafe_allow_html=True)
                elif "CCTV 2" in cam_name:
                    st.markdown(f'<img src="http://{JETSON_WIFI_IP}:5000/video_feed/CAM_02" width="{cam_width}px">', unsafe_allow_html=True)
                else:
                    st.image(VIRTUAL_STREAM_URL, width=cam_width)

st.divider()

# -----------------------------
# 2층: 위험 연산 결과 및 하드웨어 상태 분석
# -----------------------------
left_data, right_data = st.columns([1, 1])

with left_data:
    st.subheader("⚠️ 위험 시나리오 자동 연산 결과")
    scenario_cols = st.columns(3)
    
    scenarios = {
        "무단 침입": {"active": db_data["object_type"] in ["멧돼지", "들개"], "conf": int(db_data["raw_confidence"] * 100)},
        "농가 피해 위험": {"active": db_data["object_type"] in ["멧돼지", "고라니"], "conf": int(db_data["raw_confidence"] * 100)},
        "소형 유해수수": {"active": db_data["object_type"] == "너구리", "conf": int(db_data["raw_confidence"] * 100)}
    }

    for idx, (label, meta) in enumerate(scenarios.items()):
        status = "🔴 위험" if meta["active"] and meta["conf"] > 70 else "🟢 정상"
        with scenario_cols[idx]:
            with st.container(border=True):
                st.markdown(f"**{label}**")
                st.markdown(f"### {status}")
                st.caption(f"신뢰도 {meta['conf']}%")

with right_data:
    st.subheader("🚨 하드웨어 경보 및 원격 제어 상태")
    device_df = pd.DataFrame(
        [{"시스템 연동 제어 항목": k, "현재 물리 출력 상태": v} for k, v in device_state.items()]
    )
    st.dataframe(device_df, width="stretch", hide_index=True)

# -----------------------------
# 3층: 하단 로그 관리 시스템 (원격 DB 연동)
# -----------------------------
st.divider()
st.subheader("📋 전체 통합 이벤트 로그 / 야생동물 관제 이력 (MySQL DB 연동)")
if not log_df.empty:
    st.dataframe(log_df, width="stretch", hide_index=True)
else:
    st.info("새로운 데이터베이스(detection_logs)에 기록된 야생동물 이력이 아직 없습니다.")

st.logo("https://img.icons8.com/color/48/shield.png")
st.caption("🔒 지능형 야생동물 보안 코어 엔진 작동 중 - 3s 동기화 🔄")

time.sleep(3.0)  
st.rerun()
