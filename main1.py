import threading
import queue
import time
from time import sleep
import cv2
import numpy as np
from picamera2 import Picamera2
from tflite_runtime.interpreter import Interpreter
import RPi.GPIO as GPIO

# --- Servo Setup ---
GPIO.setmode(GPIO.BOARD)
GPIO.setup(11, GPIO.OUT)
servo = GPIO.PWM(11, 50)
servo.start(0)

def servo_movement(prediction_queue):
    """Control the servo based on predictions from the queue."""
    while True:
        try:
            # Wait for 10 seconds before processing the next prediction
            sleep(10)
            
            # Get the next prediction from the queue
            prediction = prediction_queue.get_nowait()  # Non-blocking, raises queue.Empty if empty
            
            # Move the servo based on the prediction
            if prediction == 1:
                servo.ChangeDutyCycle(0)  # Move left
            elif prediction == 0:
                servo.ChangeDutyCycle(12)  # Move right
                sleep(0.5)
                servo.ChangeDutyCycle(7.5)  # Center position
            # servo.ChangeDutyCycle(0)  # Stop servo
        except queue.Empty:
            print("Servo thread: Queue is empty, skipping this cycle.")

# --- Prediction Setup ---
interpreter = Interpreter(model_path="model.tflite")
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

def preprocess_image(image):
    input_shape = input_details[0]['shape']
    image = cv2.resize(image, (input_shape[1], input_shape[2]))
    image = np.expand_dims(image, axis=0).astype(np.float32)
    image /= 255.0
    return image

def predict_tflite(image):
    interpreter.set_tensor(input_details[0]['index'], image)
    interpreter.invoke()
    output_data = interpreter.get_tensor(output_details[0]['index'])
    prediction = 1 if output_data > 0.5 else 0
    return prediction

# --- Camera Setup ---
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"})
picam2.configure(config)
picam2.start()

x, y, w, h = 210, 400, 200, 200 

# --- Image Classification Thread ---
def image_classification(prediction_queue):
    """Capture images, make predictions, and add them to the queue."""
    while True:
        # Capture frame from PiCamera2
        frame = picam2.capture_array()
        roi = frame[y:y+h, x:x+w]
        
        # Preprocess and make prediction
        prediction = predict_tflite(preprocess_image(roi))
        print(f"{time.ctime()} Prediction:", prediction)

        
        # Draw outer green rectangle for subject detection area
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        # Display frame with bounding box
        cv2.imshow('Camera', frame)
        
        # Add the prediction to the queue
        if not prediction_queue.full():  # Avoid blocking if queue is full
            prediction_queue.put(prediction)
        else:
            print("Prediction queue is full. Dropping oldest prediction.")
            prediction_queue.get()  # Remove the oldest prediction
            prediction_queue.put(prediction)

# --- Main Program ---
if __name__ == "__main__":
    prediction_queue = queue.Queue(maxsize=5)  # Queue to share predictions between threads

    # Create and start threads
    prediction_thread = threading.Thread(target=image_classification, args=(prediction_queue,))
    servo_thread = threading.Thread(target=servo_movement, args=(prediction_queue,))
    prediction_thread.start()
    servo_thread.start()

    # Join threads (optional, for cleanup on program termination)
    prediction_thread.join()
    servo_thread.join()

    # Cleanup
    picam2.stop()
    cv2.destroyAllWindows()
    servo.stop()
    GPIO.cleanup()
