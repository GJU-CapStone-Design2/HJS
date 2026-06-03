import streamlit as st
import pymysql
import pandas as pd
import plotly.express as px
import time
import math

# 페이지 기본 설정
st.set_page_config(page_title="야생동물 통계 분석 대시보드", layout="wide")

# 📌 [필수 설정] 메인 파일과 동일한 광주대 DB 설정 공유
DB_CONFIG = {
    "host": "earth.gwangju.ac.kr",
    "user": "dbuser211702",
    "password": "ce1234",
    "database": "db211702",
    "charset": "utf8mb4"
}

# 📌 [UI 통일성] 모든 그래프에서 동물의 색상과 순서를 완벽하게 일치
ANIMAL_COLORS = {
    "멧돼지": "#EF553B",   # 강렬한 주황/빨강 (경고)
    "고라니": "#00CC96",   # 녹색 계열
    "너구리": "#AB63FA",   # 보라색 계열
    "들개": "#19D3F3"      # 하늘색 계열
}
FIXED_ORDER = ["멧돼지", "고라니", "너구리", "들개"]

# DB 연결 함수
def get_db_connection():
    try:
        return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)
    except Exception as e:
        st.error(f"❌ 데이터베이스 연결 실패: {e}")
        return None

# 통계 데이터 로드 함수 (하드웨어 상태 컬럼 추가 로드)
def fetch_chart_data():
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    try:
        with conn.cursor() as cursor:
            # 📌 siren_status, light_status 추가 (하드웨어 통계용)
            sql = """
                SELECT 
                    event_time, 
                    object_type, 
                    confidence,
                    siren_status,
                    light_status
                FROM detection_logs 
                ORDER BY event_time ASC
            """
            cursor.execute(sql)
            res = cursor.fetchall()
            if res:
                df = pd.DataFrame(res)
                df['event_time'] = pd.to_datetime(df['event_time'])
                df['날짜'] = df['event_time'].dt.date
                df['시간(시)'] = df['event_time'].dt.hour
                return df
    except Exception as e:
        st.error(f"데이터 연산 오류: {e}")
    finally:
        if conn: conn.close()
    return pd.DataFrame()

# -----------------------------
# 화면 렌더링 시작
# -----------------------------
st.title("야생동물 출현 통계 및 트렌드 분석")

df = fetch_chart_data()

if df.empty:
    st.info("DB에 축적된 탐지 로그가 없어 그래프를 표시할 수 없습니다.")
else:
    # -----------------------------
    # 1층: 상단 요약 지표 (Metrics)
    # -----------------------------
    total_count = len(df)
    boar_count = len(df[df['object_type'] == '멧돼지'])
    avg_conf = df['confidence'].mean() * 100

    m1, m2, m3 = st.columns(3)
    m1.metric("총 누적 탐지 건수", f"{total_count} 건")
    m2.metric("멧돼지 출현 건수", f"{boar_count} 건", delta=f"전체의 {boar_count/total_count*100:.1f}%" if total_count > 0 else "0%")
    m3.metric("평균 AI 신뢰도", f"{avg_conf:.1f}%")

    st.divider()

    # -----------------------------
    # 2층: 메인 시각화 레이아웃 (색상 및 순서 고정 완벽 적용)
    # -----------------------------
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("24시간 야생동물 출현 트렌드")
        time_trend = df.groupby(['시간(시)', 'object_type']).size().reset_index(name='탐지 횟수')
        
        fig_line = px.line(
            time_trend, 
            x='시간(시)', 
            y='탐지 횟수', 
            color='object_type',
            markers=True,
            labels={'시간(시)': '시간 (24시)', '탐지 횟수': '출현 횟수', 'object_type': '동물 종류'},
            title="하루 중 어느 시간대에 가장 많이 나타났을까?",
            color_discrete_map=ANIMAL_COLORS,
            category_orders={"object_type": FIXED_ORDER} # 👈 순서 고정
        )
        fig_line.update_layout(xaxis=dict(tickmode='linear', tick0=0, dtick=2))
        st.plotly_chart(fig_line, use_container_width=True)

    with col2:
        st.subheader("야생동물 종류별 탐지 비율")
        type_counts = df['object_type'].value_counts().reset_index()
        type_counts.columns = ['동물 종류', '지정 건수']
        
        fig_bar = px.bar(
            type_counts, 
            x='동물 종류', 
            y='지정 건수',
            color='동물 종류',
            text_auto=True,
            labels={'지정 건수': '총 탐지 횟수'},
            title="위험 동물별 누적 발견 비교",
            color_discrete_map=ANIMAL_COLORS,
            category_orders={"동물 종류": FIXED_ORDER} # 👈 순서 고정
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()


    # -----------------------------
    # 4층: 하단 타겟 동물 선택형 집중 분석 섹션 (페이지네이션 포함)
    # -----------------------------
    st.divider()
    
    available_animals = df['object_type'].unique().tolist()
    if not available_animals:
        available_animals = ["멧돼지"]
        
    st.subheader("선택 관측 데이터 정밀 분석")
    
    selected_target = st.selectbox("분석할 대상을 선택하세요:", available_animals, index=0)
    
    target_df = df[df['object_type'] == selected_target].sort_values(by='event_time', ascending=False)
    
    if target_df.empty:
        st.success(f"✅ 최근 데이터 중 {selected_target} 감지 이력이 없습니다. 안전 상태입니다.")
    else:
        b_col1, b_col2 = st.columns([1, 2])
        with b_col1:
            st.warning(f"⚠️ {selected_target} 탐지 이력 및 신뢰도 로그 리스트입니다.")
            
            # 페이지네이션 데이터프레임
            display_df = target_df[['event_time', 'confidence']].rename(
                columns={'event_time': '감지 시각', 'confidence': '신뢰도'}
            ).reset_index(drop=True)
            
            total_rows = len(display_df)
            rows_per_page = 10  # 한 번에 보여줄 행 개수
            max_page = math.ceil(total_rows / rows_per_page)
            
            if f"page_{selected_target}" not in st.session_state:
                st.session_state[f"page_{selected_target}"] = 1
                
            current_page = st.session_state[f"page_{selected_target}"]
            
            if current_page > max_page and max_page > 0:
                current_page = max_page
                st.session_state[f"page_{selected_target}"] = max_page

            start_idx = (current_page - 1) * rows_per_page
            end_idx = start_idx + rows_per_page
            paginated_df = display_df.iloc[start_idx:end_idx]
            
            # 표 출력
            st.dataframe(paginated_df, hide_index=True, use_container_width=True)
            
            # ◀ 이전 | 다음 ▶ 버튼 제어기
            page_col1, page_col2, page_col3 = st.columns([1, 2, 1])
            with page_col1:
                if st.button("◀ 이전", disabled=(current_page == 1), key=f"prev_{selected_target}"):
                    st.session_state[f"page_{selected_target}"] -= 1
                    st.rerun()
            with page_col2:
                st.markdown(f"<center>{current_page} / {max_page if max_page > 0 else 1} 페이지 (총 {total_rows}건)</center>", unsafe_allow_html=True)
            with page_col3:
                if st.button("다음 ▶", disabled=(current_page == max_page or max_page == 0), key=f"next_{selected_target}"):
                    st.session_state[f"page_{selected_target}"] += 1
                    st.rerun()

        with b_col2:
            # 일자별 선택 동물 출현 추이 그래프
            daily_target = target_df.groupby('날짜').size().reset_index(name='출현 횟수')
            target_color = ANIMAL_COLORS.get(selected_target, '#ef553b')
            
            fig_target_daily = px.area(
                daily_target, 
                x='날짜', 
                y='출현 횟수', 
                title=f"📆 일자별 {selected_target} 출현 빈도 추이",
                color_discrete_sequence=[target_color]
            )
            st.plotly_chart(fig_target_daily, use_container_width=True)

# ⚙️ 5초마다 데이터 동기화 리프레시 코드
st.caption("🔄 관제 통계 엔진 작동 중 - 5s 간격 자동 동기화")
time.sleep(5.0)
st.rerun()
