import cv2
import time
import numpy as np
from ultralytics import YOLO
import pygame
import datetime
import os
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize pygame for playing the alarm sound
pygame.mixer.init()
alarm_sound = 'static/alarm/peringatan.mp3'

# Load the YOLOv8 model with tracking support
model = YOLO('static/model/031924.pt')

# Dictionary to hold car information
car_dict = {}

# Set to hold active car IDs
active_cars = set()

# Dictionary to hold timer information for each car
timers = {}

# Dictionary to hold alarm status for each car
alarms = {}

# Twilio client setup
ACCOUNT_SID = os.getenv('ACCOUNT_SID')
AUTH_TOKEN = os.getenv('AUTH_TOKEN_WA')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER_WA')
client = Client(ACCOUNT_SID, AUTH_TOKEN)

# Function to play the alarm sound
def Auto_alarm():
    if not pygame.mixer.music.get_busy():  # Check if the alarm is not already playing
        pygame.mixer.music.load(alarm_sound)
        pygame.mixer.music.play()

# Function to send WhatsApp message
def send_whatsapp_message(to_number, message_body):
    try:
        message = client.messages.create(
            body=message_body,
            from_=TWILIO_PHONE_NUMBER,
            to=f'whatsapp:{to_number}'
        )
        return {'status': 'Message sent', 'sid': message.sid}
    except TwilioRestException as e:
        return {'error': str(e)}
    except Exception as e:
        return {'error': 'An unexpected error occurred: ' + str(e)}

# Function to send alarm message to security contacts
def send_alarm_message(contacts):
    message = "🚨 *SEGERA KEAREA DROPOFF ZONE !!* 🚨📢\n\nSedang terjadi penumpukan lalulintas *DIAREA DROPOFF ZONE* \n\nTolong security agar segera kelokasi !!!"
    for contact in contacts:
        response = send_whatsapp_message(contact, message)
        if 'error' in response:
            print(f"Failed to send message to {contact}: {response['error']}")
        else:
            print(f"Message sent to {contact}: SID {response['sid']}")

# Function to update car information with elapsed time
def update_car_info(car_id, elapsed_time):
    car_dict[car_id] = f"Id: {car_id} | Time: {elapsed_time:.2f}s"

# Function to reset car information
def reset_car_info(car_id):
    car_dict[car_id] = f"Id: {car_id} | Time: 0s"

# Function to check if the car is within the zone
def is_within_zone(center, zone):
    zone_polygon = np.array(zone, np.int32)
    return cv2.pointPolygonTest(zone_polygon, center, False) >= 0

# Function to detect and track cars
def detect_and_track_cars(frame, model, zone, active_cars, timers, alarms, insert_dropoff, update_dropoff, contacts, alarm_threshold):
    results = model.track(source=frame, tracker='bytetrack.yaml')
    
    # Check if results contain detected objects
    if not hasattr(results[0], 'boxes') or results[0].boxes is None:
        return frame
    
    # Extract the tracked objects from the results
    if results[0].boxes.xywh is not None:
        tracked_objects = results[0].boxes.xywh.cpu().numpy() 
    else:
        tracked_objects = np.array([])
        
    if results[0].boxes.id is not None:
        ids = results[0].boxes.id.cpu().numpy()
    else:
        ids = np.array([])

    current_car_ids = set()
    current_time = time.time()

    cv2.polylines(frame, [np.array(zone, np.int32)], isClosed=True, color=(255, 0, 0, 10), thickness=2)

    # Check if there are any tracked objects and ids
    if tracked_objects.size == 0 or ids.size == 0:
        return frame

    for i, (x, y, w, h) in enumerate(tracked_objects):
        car_id = int(ids[i])  # Use the tracking ID provided by the tracker
        car_center = (int(x), int(y))
        x1, y1, x2, y2 = int(x - w/2), int(y - h/2), int(x + w/2), int(y + h/2)
        center_x, center_y = int((x1 + x2) / 2), int((y1 + y2) / 2)  # Calculate center coordinates
        
        # Check if car is within the zone
        if is_within_zone(car_center, zone):
            if car_id not in active_cars:
                timers[car_id] = current_time
                active_cars.add(car_id)
                alarms[car_id] = False  # Initialize alarm status
                waktu_masuk = datetime.datetime.now()
                update_car_info(car_id, 0)
                insert_dropoff(car_id, waktu_masuk)

            elapsed_time = current_time - timers[car_id]
            update_car_info(car_id, elapsed_time)

            # Trigger alarm if the car stays in the zone for more than the specified threshold
            if elapsed_time > alarm_threshold:
                if not alarms[car_id]:  # Check if the alarm for this car has already been triggered
                    send_alarm_message(contacts)  # Send alarm message only once
                    alarms[car_id] = True  # Mark this alarm as triggered
                Auto_alarm()  # Play the alarm sound continuously
        else:
            if car_id in active_cars:
                reset_car_info(car_id)
                active_cars.remove(car_id)
                waktu_keluar = datetime.datetime.now()
                update_dropoff(car_id, waktu_keluar)
                if car_id in timers:
                    del timers[car_id]
                if car_id in alarms:
                    del alarms[car_id]
            else:
                reset_car_info(car_id)  # Display time as 0 if not in the zone

        current_car_ids.add(car_id)

        # Draw bounding box and ID
        if car_id in car_dict:
            cv2.putText(frame, car_dict[car_id], (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            cv2.circle(frame, (center_x, center_y), 5, (0, 0, 255), -1)

    # Clean up car_dict for cars that are no longer in the frame
    for car_id in list(car_dict.keys()):
        if car_id not in current_car_ids:
            reset_car_info(car_id)
            if car_id in active_cars:
                active_cars.remove(car_id)
            if car_id in timers:
                del timers[car_id]
            if car_id in alarms:
                del alarms[car_id]

    return frame
