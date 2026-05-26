import cv2
import numpy as np
import time
from ultralytics import YOLO

def run_speed_test_pipeline():
    print("[INFO] 속도 측정용 파이프라인 로드 중...")
    
    yolo_model = YOLO("yolo11n.pt")
    yolo_model.to('cpu')
    
    net_dce = cv2.dnn.readNetFromONNX("zero_dce_sim.onnx")
    # OpenCV CUDA는 직접 빌드하지 않으면 작동안하므로 일단 기본값(CPU)으로 둡니다.

    cap = cv2.VideoCapture(0) # 웹캠 기준 (유튜브면 스트림 URL)
    if not cap.isOpened(): return

    print("\n[INFO] 속도 테스트 시작!")

    while True:
        # 전체 프레임 시작 시간
        loop_start = time.time()
        
        ret, frame = cap.read()
        if not ret: break
        
        # 1. 카메라 읽기 속도 측정
        read_time = time.time() - loop_start

        frame = cv2.resize(frame, (640, 480))

        # ----------------------------------------------------
        # [STEP 1] Zero-DCE (ONNX)
        # ----------------------------------------------------
        dce_start = time.time()
        blob = cv2.dnn.blobFromImage(frame, 1.0/255.0, (640, 480), (0, 0, 0), swapRB=True, crop=False)
        net_dce.setInput(blob)
        outputs = net_dce.forward(net_dce.getUnconnectedOutLayersNames())
        rgb_outputs = [out for out in outputs if len(out.shape) == 4 and out.shape[1] == 3]
        enhanced_frame = np.squeeze(rgb_outputs[-1]) 
        enhanced_frame = np.transpose(enhanced_frame, (1, 2, 0))
        enhanced_frame = cv2.cvtColor(enhanced_frame, cv2.COLOR_RGB2BGR) 
        enhanced_frame = (np.clip(enhanced_frame, 0, 1) * 255.0).astype(np.uint8)
        
        # DCE 처리 시간 계산
        dce_time = time.time() - dce_start

        # ----------------------------------------------------
        # [STEP 2] YOLO11
        # ----------------------------------------------------
        yolo_start = time.time()
        results = yolo_model(enhanced_frame, verbose=False)
        final_frame = results[0].plot()
        
        # YOLO 처리 시간 계산
        yolo_time = time.time() - yolo_start

        # ----------------------------------------------------
        # 화면 출력 및 FPS 계산
        # ----------------------------------------------------
        total_time = time.time() - loop_start
        fps = 1.0 / total_time if total_time > 0 else 0

        combined_frame = cv2.hconcat([frame, final_frame])
        
        # 화면에 속도 정보 띄우기
        cv2.putText(combined_frame, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.putText(combined_frame, f"Cam Load: {read_time:.3f}s", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(combined_frame, f"Zero-DCE: {dce_time:.3f}s", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(combined_frame, f"YOLO11: {yolo_time:.3f}s", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        cv2.imshow("Speed Diagnostics", combined_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'): break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_speed_test_pipeline()