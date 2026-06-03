import os
import cv2
import threading
import time
import serial
import pymysql
import datetime
import pygame
import numpy as np
from flask import Flask, request, jsonify, Response, send_from_directory
from ultralytics import YOLO

# 💡 [핵심 패치 1] 캡처 이미지를 저장할 로컬 폴더 생성
CAPTURE_DIR = "captures"
os.makedirs(CAPTURE_DIR, exist_ok=True)
JETSON_WIFI_IP = "220.69.20.133" 

# 💡 [오디오 경로 및 버퍼 최적화 패치] 
# 프로그램 실행 위치와 상관없이 무조건 같은 폴더의 .wav를 찾도록 절대 경로로 빌드합니다.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SIREN_PATH = os.path.join(BASE_DIR, "siren.wav")
PERSON_PATH = os.path.join(BASE_DIR, "person.wav")

try:
    # 젯슨 나노 하드웨어 가속 및 음성 딜레이 방지를 위한 사전 버퍼 세팅
    pygame.mixer.pre_init(44100, -16, 2, 2048)
    pygame.mixer.init()
    print("[INFO] Pygame 오디오 믹서 엔진 초기화 성공!")
except Exception as e:
    print(f"[ERROR] Pygame 오디오 믹서 초기화 실패 (하드웨어 꼬임): {e}")

# 💡 에러가 나면 터미널에 정확한 이유를 출력합니다.
try:
    if os.path.exists(SIREN_PATH):
        siren_sound = pygame.mixer.Sound(SIREN_PATH)
        print("[INFO] siren.wav 사운드 파일 로드 성공 완료")
    else:
        print(f"[WARNING] 파일 없음: {SIREN_PATH} 경로에 파일이 존재하지 않습니다.")
        siren_sound = None
except Exception as e:
    print(f"[ERROR] siren.wav 로드 중 실패 발생: {e}")
    siren_sound = None

try:
    if os.path.exists(PERSON_PATH):
        person_sound = pygame.mixer.Sound(PERSON_PATH)
        print("[INFO] person.wav 사운드 파일 로드 성공 완료")
    else:
        print(f"[WARNING] 파일 없음: {PERSON_PATH} 경로에 파일이 존재하지 않습니다.")
        person_sound = None
except Exception as e:
    print(f"[ERROR] person.wav 로드 중 실패 발생: {e}")
    person_sound = None
    
# ==========================================
# [Zero-DCE 모델 로드 및 상태 변수]
# ==========================================
DCE_ENABLED = False  # 기본값: 꺼짐(False)

try:
    print("[INFO] Zero-DCE 저조도 강화 모델 로드 중...")
    # 💡 [수정 완료] OpenCV 에러 방지를 위해 친구의 sim 버전 파일명으로 변경
    net_dce = cv2.dnn.readNetFromONNX("zero_dce_sim.onnx")
    print("[INFO] Zero-DCE 로드 성공!")
except Exception as e:
    print(f"[ERROR] Zero-DCE 로드 실패: {e}")
    net_dce = None

# 친구 코드에서 추출한 마법의 변환 함수
def enhance_image(frame, net):
    if net is None: return frame
    
    frame_resized = cv2.resize(frame, (640, 480))
    blob = cv2.dnn.blobFromImage(frame_resized, 1.0/255.0, (640, 480), (0, 0, 0), swapRB=True, crop=False)
    net.setInput(blob)
    outputs = net.forward(net.getUnconnectedOutLayersNames())
    
    rgb_outputs = [out for out in outputs if len(out.shape) == 4 and out.shape[1] == 3]
    enhanced_frame = np.squeeze(rgb_outputs[-1]) 
    enhanced_frame = np.transpose(enhanced_frame, (1, 2, 0))
    enhanced_frame = cv2.cvtColor(enhanced_frame, cv2.COLOR_RGB2BGR) 
    enhanced_frame = (np.clip(enhanced_frame, 0, 1) * 255.0).astype(np.uint8)
    
    # 젯슨 렉 방지를 위해 다시 원래 크기로 돌려놓음
    return cv2.resize(enhanced_frame, (frame.shape[1], frame.shape[0]))

# ==========================================
# [설정 및 전역 변수]
# ==========================================
current_filters = ["wild_boar", "water_deer", "raccoon_dog", "wild_dog"]

CLASS_MAPPING = {
    0: "person",          
    67: "cell_phone",     
    16: "wild_boar", 
    17: "water_deer", 
    18: "raccoon_dog", 
    19: "wild_dog"
}

KOR_MAPPING = {
    "person": "사람(테스트)",
    "cell_phone": "핸드폰(테스트)",
    "wild_boar": "멧돼지", 
    "water_deer": "고라니", 
    "raccoon_dog": "너구리", 
    "wild_dog": "들개"
}

DB_CONFIG = {
    "host": "earth.gwangju.ac.kr",
    "user": "dbuser211702",
    "password": "ce1234",
    "database": "db211702",
    "charset": "utf8mb4"
}

latest_frames = {"CAM_01": None, "CAM_02": None}
frame_lock = threading.Lock()

ARDUINO_PORT = '/dev/ttyACM0' 
LAST_ALERT_TIME = 0
ALERT_COOLTIME = 10

# ------------------------------------------
# 🔌 아두이노 시리얼 통신 초기화
# ------------------------------------------
try:
    arduino = serial.Serial(port=ARDUINO_PORT, baudrate=9600, timeout=1)
    time.sleep(2.0)
    print(f"[INFO] 아두이노 연결 성공 ({ARDUINO_PORT}) - 통신 준비 완료!")
except Exception as e:
    print(f"[WARNING] 아두이노 연결 실패: {e}")
    arduino = None

# 💡 [기능 통합 변경] 어떤 객체인지 판단해서 소리를 분기 재생하는 함수
def play_sound(animal_code):
    """사람이면 특정 안내 음성, 동물이면 기존 비상 사이렌 재생"""
    if animal_code == "person":
        if person_sound:
            print("[AUDIO] 🗣️ 사람 안내 방송 재생 시작 (person.wav)")
            person_sound.play()
            time.sleep(3) 
            person_sound.stop()
        else:
            print("[AUDIO ⚠️] person.wav 인스턴스가 존재하지 않아 재생을 건너뜁니다.")
    else:
        if siren_sound:
            print("[AUDIO] 🚨 야생동물 격리 사이렌 재생 시작 (siren.wav)")
            siren_sound.play()
            time.sleep(3) 
            siren_sound.stop()
        else:
            print("[AUDIO ⚠️] siren.wav 인스턴스가 존재하지 않아 재생을 건너뜁니다.")

# ==========================================
# 📌 실시간 DB 저장 쓰레드 함수
# ==========================================
def insert_db_log(animal_code, conf, image_url):
    try:
        conn = pymysql.connect(**DB_CONFIG)
        kor_name = KOR_MAPPING.get(animal_code, animal_code)
        
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO detection_logs 
                (event_time, object_type, confidence, siren_status, light_status, alert_status, remarks, image_path) 
                VALUES (NOW(), %s, %s, 'Y', 'Y', 'PENDING', 'AI 실시간 시스템 자동 감지', %s)
            """
            cursor.execute(sql, (kor_name, float(conf), image_url))
        
        conn.commit()
        conn.close()
        print(f"[DB 업로드 성공] {kor_name} 저장 완료!")
    except Exception as e:
        print(f"[DB 연동 실패] {e}")

# ==========================================
# [통신 및 스트리밍 서버 (Flask)]
# ==========================================
app = Flask(__name__)

@app.route('/captures/<path:filename>')
def serve_capture(filename):
    return send_from_directory(CAPTURE_DIR, filename)

@app.route('/set_filter', methods=['POST'])
def set_filter():
    global current_filters
    current_filters = request.json.get("filter_codes", [])
    print(f"\n[필터 업데이트] 현재 감시 대상: {current_filters}")
    return jsonify({"status": "success"})
    
@app.route('/toggle_dce', methods=['POST'])
def toggle_dce():
    global DCE_ENABLED
    # 웹에서 보낸 켜기/끄기 값을 받아서 전역 변수에 저장
    DCE_ENABLED = request.json.get("dce_on", False)
    status_str = "ON" if DCE_ENABLED else "OFF"
    print(f"\n[웹 제어] 💡 Zero-DCE 모드가 {status_str} 되었습니다!")
    return jsonify({"status": "success", "dce_enabled": DCE_ENABLED})

def generate_mjpeg(cam_id):
    while True:
        with frame_lock:
            frame = latest_frames.get(cam_id)
        if frame is None:
            time.sleep(0.1)
            continue
        
        ret, jpeg = cv2.imencode('.jpg', frame)
        if ret:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n\r\n')
        time.sleep(0.03)

@app.route('/video_feed/<cam_id>')
def video_feed(cam_id):
    return Response(generate_mjpeg(cam_id), mimetype='multipart/x-mixed-replace; boundary=frame')

def run_api_server():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ==========================================
# 🚀 [카메라 멀티쓰레드 캡처 - 소스 스위칭 기능 추가]
# ==========================================
class CameraStreamer:
    def __init__(self, camera_id, src=0):
        self.camera_id = camera_id
        self.src = src # 현재 소스(웹캠 번호 또는 영상 경로) 저장
        self.cap = cv2.VideoCapture(src)
        self.ret, self.frame = False, None
        self.started = False
        self.lock = threading.Lock()

    def start(self):
        self.started = True
        self.thread = threading.Thread(target=self.update, daemon=True)
        self.thread.start()
        return self

    def update(self):
        while self.started:
            ret, frame = self.cap.read()
            
            # 💡 [핵심] 시연 영상(.mp4)이 끝까지 재생되면 다시 처음으로 되감기(Loop)
            if not ret and isinstance(self.src, str):
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
                
            with self.lock:
                self.ret, self.frame = ret, frame
            time.sleep(0.01)

    def get_frame(self):
        with self.lock:
            if self.ret and self.frame is not None: return True, self.frame.copy()
            return False, None

    def stop(self):
        self.started = False
        self.cap.release()

    # 💡 [핵심] 런타임 중에 카메라 소스를 갈아끼우는 치트키 함수
    def change_source(self, new_src):
        with self.lock:
            if self.cap:
                self.cap.release()
            self.src = new_src
            self.cap = cv2.VideoCapture(new_src)
            print(f"\n[🎥 소스 전환 성공] {self.camera_id} ➔ {new_src}")

# ==========================================
# [메인 YOLO 루프]
# ==========================================
def main():
    # 💡 [수정 완료] DCE_ENABLED 전역 변수 선언 추가 (UnboundLocalError 해결)
    global current_filters, LAST_ALERT_TIME, latest_frames, DCE_ENABLED

    # 오타 수정: yolo11s -> yolov11n.pt
    model = YOLO('yolov11n.pt') 

    threading.Thread(target=run_api_server, daemon=True).start()
    print("[INFO] 통신 서버 가동 완료 (Port: 5000)")

    cam1 = CameraStreamer("CAM_01", 0).start()
    cam2 = CameraStreamer("CAM_02", 2).start() 
    time.sleep(1.0)
    print("\n[INFO] YOLO 루프 시작!")
    print("📢 [시연 치트키 안내] 'Live Monitor' 창을 클릭한 상태에서 키보드를 누르세요.")
    print("   - 'v' 누르기: 1번 캠을 준비된 멧돼지 영상(demo_boar.mp4)으로 전환")
    print("   - 'c' 누르기: 1번 캠을 다시 실제 라이브 웹캠(0)으로 복구\n")

    try:
        while True:
            # 💡 키보드 입력을 받기 위한 OpenCV 대기열 (1ms 단위)
            key = cv2.waitKey(1) & 0xFF
            
            # 'v' 키를 누르면 영상으로 스위칭
            if key == ord('v'):
                print("🎬 [치트키 발동] 1번 카메라에 'demo_boar.mp4' 영상을 주입합니다!")
                cam1.change_source("demo_boar.mp4")
                
            # 'c' 키를 누르면 실제 웹캠으로 스위칭
            elif key == ord('c'):
                print("📷 [치트키 발동] 1번 카메라를 실제 웹캠(0)으로 복구합니다!")
                cam1.change_source(0)
                
            # 💡 [핵심] 'z' 키를 누르면 화면 밝기 모드 토글 (웹 버튼 고장 대비 보험)
            elif key == ord('z'):
                DCE_ENABLED = not DCE_ENABLED
                status = "ON" if DCE_ENABLED else "OFF"
                print(f"💡 [치트키 발동] Zero-DCE 야간 투시 모드 {status}!")

            active_cams = [cam1, cam2] 
            
            for cam in active_cams:
                success, frame = cam.get_frame()
                if not success: continue
                
                # 💡 [핵심] DCE_ENABLED가 True일 때만 프레임을 밝게 세탁함!
                if DCE_ENABLED:
                    frame = enhance_image(frame, net_dce)

                results = model(frame, stream=True, verbose=False)

                for r in results:
                    for box in r.boxes:
                        class_id = int(box.cls[0])
                        conf = float(box.conf[0])

                        if class_id in CLASS_MAPPING:
                            animal_code = CLASS_MAPPING[class_id]
                            
                            if animal_code in current_filters:
                                if conf > 0.6:
                                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                                    cv2.putText(frame, animal_code, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                                    current_time = time.time()
                                    if current_time - LAST_ALERT_TIME > ALERT_COOLTIME:
                                        print(f"🚨 {animal_code} 탐지! 시스템 경보 아키텍처 가동!")
                                        
                                        timestamp_str = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                                        filename = f"{timestamp_str}_{animal_code}.jpg"
                                        filepath = os.path.join(CAPTURE_DIR, filename)
                                        cv2.imwrite(filepath, frame)
                                        
                                        image_url = f"http://{JETSON_WIFI_IP}:5000/captures/{filename}"
                                        
                                        if arduino and arduino.is_open: 
                                            arduino.write(b'W\n')
                                            arduino.flush() 
                                            
                                        threading.Thread(target=insert_db_log, args=(animal_code, conf, image_url), daemon=True).start()
                                        
                                        threading.Thread(target=play_sound, args=(animal_code,), daemon=True).start()
                                        
                                        LAST_ALERT_TIME = current_time

                # 💡 [핵심] 키보드 이벤트를 받기 위해 화면에 모니터링 창을 띄웁니다.
                if cam.camera_id == "CAM_01":
                    cv2.imshow("Live Monitor (Press 'v' for Video, 'c' for Cam)", frame)

                with frame_lock:
                    latest_frames[cam.camera_id] = frame
                    
            time.sleep(0.01)

    except KeyboardInterrupt: pass
    finally:
        cam1.stop()
        cam2.stop()
        if arduino: arduino.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
