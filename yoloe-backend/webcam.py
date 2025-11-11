import os
import cv2
from ultralytics import YOLO

# Get the directory where webcam.py is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(SCRIPT_DIR, "yolov8n.pt")

def main():
    # Initialize webcam
    cap = cv2.VideoCapture(0)
    
    # Load YOLO model from the correct path
    model = YOLO(MODEL_PATH)
    
    while cap.isOpened():
        # Read frame
        success, frame = cap.read()
        if success:
            # Run YOLOv8 inference on the frame
            results = model(frame)

            # Visualize the results on the frame
            annotated_frame = results[0].plot()

            # Display the annotated frame
            cv2.imshow("YOLOv8 Inference", annotated_frame)

            # Break the loop if 'q' is pressed
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        else:
            break

    # Release the video capture object and close the display window
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
