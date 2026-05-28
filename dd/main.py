import cv2
import threading
import time
import serial
from flask import Flask, request, jsonify, Response
from ultralytics import YOLO

# ==========================================
# [설정 및 전역 변수]
# ==========================================
# 대시보드 초기 필터값 설정
current_filter = "all"
CLASS_MAPPING = {16: "wild_boar", 17: "water_deer", 18: "raccoon_dog", 19: "wild_dog"}

# 영상 스트리밍을 위해 최신 프레임을 담아둘 공유 메모리
latest_frames = {"CAM_01": None, "CAM_02": None}
frame_lock = threading.Lock()

# 아두이노 포트 설정
ARDUINO_PORT = '/dev/ttyACM0' 
LAST_ALERT_TIME = 0
ALERT_COOLTIME = 5

try:
    arduino = serial.Serial(port=ARDUINO_PORT, baudrate=9600, timeout=1)
    print(f"[INFO] 아두이노 연결 성공 ({ARDUINO_PORT})")
except Exception as e:
    print(f"[WARNING] 아두이노 연결 실패: {e}")
    arduino = None

# ==========================================
# [통신 및 스트리밍 서버 (Flask)]
# ==========================================
app = Flask(__name__)

# 1. 대시보드에서 날아오는 필터 변경 신호(POST) 수신
@app.route('/set_filter', methods=['POST'])
def set_filter():
    global current_filter
    current_filter = request.json.get("filter_code", "all")
    print(f"\n[대시보드 수신] 타겟 필터가 '{current_filter}'(으)로 변경되었습니다.")
    return jsonify({"status": "success"})

# 2. 대시보드로 실시간 영상(MJPEG) 쏴주기
def generate_mjpeg(cam_id):
    while True:
        with frame_lock:
            frame = latest_frames.get(cam_id)
        if frame is None:
            time.sleep(0.1)
            continue
        
        # 프레임을 JPEG로 압축하여 송출 (대시보드 브라우저가 이 데이터를 받아 영상으로 띄움)
        ret, jpeg = cv2.imencode('.jpg', frame)
        if ret:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n\r\n')
        time.sleep(0.03)

@app.route('/video_feed/<cam_id>')
def video_feed(cam_id):
    return Response(generate_mjpeg(cam_id), mimetype='multipart/x-mixed-replace; boundary=frame')

def run_api_server():
    # 0.0.0.0으로 열어야 폰(동일 와이파이)에서도 접속 가능
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ==========================================
# [카메라 멀티쓰레드 캡처]
# ==========================================
class CameraStreamer:
    def __init__(self, camera_id, src=0):
        self.camera_id = camera_id
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

# ==========================================
# [메인 YOLO 루프]
# ==========================================
def main():
    global current_filter, LAST_ALERT_TIME, latest_frames

    # YOLO 모델 로드 (.engine 변환 파일 권장)
    model = YOLO('yolov11n.pt') 

    # 통신 서버 백그라운드 가동
    threading.Thread(target=run_api_server, daemon=True).start()
    print("[INFO] 웹 스트리밍 및 API 서버 가동 완료 (Port: 5000)")

    # 카메라 2대 시작
    cam1 = CameraStreamer("CAM_01", 0).start()
    cam2 = CameraStreamer("CAM_02", 1).start()
    time.sleep(1.0)
    print("[INFO] YOLO 실시간 탐지 루프 시작...")

    try:
        while True:
            for cam in [cam1, cam2]:
                success, frame = cam.get_frame()
                if not success: continue

                # YOLO 추론
                results = model(frame, stream=True, verbose=False)

                for r in results:
                    for box in r.boxes:
                        class_id = int(box.cls[0])
                        conf = float(box.conf[0])

                        # 대시보드 필터 적용
                        if class_id in CLASS_MAPPING:
                            animal_code = CLASS_MAPPING[class_id]
                            
                            if current_filter == "all" or current_filter == animal_code:
                                if conf > 0.6:
                                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                                    cv2.putText(frame, animal_code, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                                    # 아두이노 알림 트리거
                                    current_time = time.time()
                                    if current_time - LAST_ALERT_TIME > ALERT_COOLTIME:
                                        print(f"🚨 {animal_code} 탐지! 아두이노 작동!")
                                        if arduino and arduino.is_open: arduino.write(b'W\n')
                                        LAST_ALERT_TIME = current_time

                # 가공 완료된 프레임을 스트리밍용 공유 메모리에 덮어쓰기
                with frame_lock:
                    latest_frames[cam.camera_id] = frame

            # 메인 시스템 자체 화면 출력 여부 (필요시 활성화)
            # cv2.imshow("Main Monitor", latest_frames["CAM_01"])
            # if cv2.waitKey(1) & 0xFF == ord('q'): break
            time.sleep(0.01)

    except KeyboardInterrupt: pass
    finally:
        cam1.stop()
        cam2.stop()
        if arduino: arduino.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()