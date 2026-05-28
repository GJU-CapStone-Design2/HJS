import pymysql

# 광주대 외부 DB 설정 정보
DB_CONFIG = {
    "host": "earth.gwangju.ac.kr",
    "user": "dbuser211702",
    "password": "ce1234",
    "database": "db211702",
    "charset": "utf8mb4"
}

print("🌐 광주대 DB 서버 연결 시도 중...")

try:
    # 1. DB 연결 테스트
    conn = pymysql.connect(**DB_CONFIG)
    print("✅ 1단계: 데이터베이스 서버 연결 성공!")
    
    # 2. 테이블 접속 및 데이터 조회 테스트
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM detection_logs;")
        row_count = cursor.fetchone()[0]
        print(f"✅ 2단계: 'detection_logs' 테이블 접근 성공!")
        print(f"📊 현재 테이블에 저장된 총 데이터 개수: {row_count}개")
        
    conn.close()
    print("\n🎉 축하합니다! DB 연동이 완벽하게 정상 작동하고 있습니다.")

except Exception as e:
    print("\n❌ DB 연결 실패!")
    print(f"🚨 에러 원인: {e}")
    print("\n💡 [체크리스트]")
    print("1. 학교 실험실이나 집의 인터넷 환경이 외부 DB 접속을 막고 있는지 확인 (방화벽 문제)")
    print("2. 아이디(user)나 비밀번호가 대소문자까지 정확하게 맞는지 확인")