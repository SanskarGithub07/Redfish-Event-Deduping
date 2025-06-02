import json
import logging
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import threading

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

event_cache = {}
cache_lock = threading.Lock()

def generate_event_key(event):
    message_id = event.get('MessageId', event.get('MessageID', 'Unknown'))
    event_type = event.get('EventType', 'Unknown')
    device_id = event.get('DeviceId', 'Unknown')
    severity = event.get('Severity', 'Unknown')
    
    origin = event.get('OriginOfCondition', {})
    origin_id = origin.get('@odata.id', 'Unknown')
    
    message_args = "_".join(map(str, event.get('MessageArgs', [])))
    
    key_elements = [message_id, event_type, device_id, severity, origin_id]
    
    if message_args:
        key_elements.append(message_args)
    
    return "|".join(key_elements)

def is_duplicate_event(event):
    dedup_window = event.get('DeduplicationTimeWindow', 0)
    
    if dedup_window <= 0:
        return False
    
    event_key = generate_event_key(event)
    current_time = datetime.now()
    
    with cache_lock:
        if event_key in event_cache:
            last_event = event_cache[event_key]
            time_diff = current_time - last_event["timestamp"]
            
            if time_diff.total_seconds() < dedup_window:
                last_event["count"] += 1
                logger.info(f"Duplicate event detected. Count: {last_event['count']}")
                return True
        
        event_cache[event_key] = {
            "timestamp": current_time,
            "count": 1
        }
        return False

def clean_event_cache():
    current_time = datetime.now()
    to_remove = []
    
    with cache_lock:
        for key, event_data in event_cache.items():
            if (current_time - event_data["timestamp"]).total_seconds() > 3600:
                to_remove.append(key)
        
        for key in to_remove:
            del event_cache[key]
    
    if to_remove:
        logger.info(f"Cleaned {len(to_remove)} expired events from cache")

def execute_actions(actions, event_data):
    if not actions:
        logger.info("No actions specified for this event")
        return
    
    logger.info(f"Executing actions: {', '.join(actions)}")
    
    for action in actions:
        if action == "NotifyAdmin":
            logger.info(f"ACTION: Would notify admin about {event_data.get('Message', 'an event')}")
        elif action == "ShutdownServer":
            logger.info(f"ACTION: Would initiate shutdown for device {event_data.get('DeviceId', 'Unknown')}")
        elif action == "LogChange":
            logger.info(f"ACTION: Would log change to event database")
        elif action == "MonitorTemperature":
            logger.info(f"ACTION: Would increase temperature monitoring frequency")
        elif action == "InitializeDrive":
            logger.info(f"ACTION: Would initialize drive at {event_data.get('OriginOfCondition', {}).get('@odata.id', 'Unknown')}")
        elif action == "UpdateInventory":
            logger.info(f"ACTION: Would update inventory database for device {event_data.get('DeviceId', 'Unknown')}")
        elif action == "CheckPowerSupplies":
            logger.info(f"ACTION: Would schedule power supply diagnostics")
        else:
            logger.info(f"ACTION: Unknown action '{action}'")

@app.route('/events', methods=['POST'])
def receive_event():
    if not request.is_json:
        logger.error("Received non-JSON request")
        return jsonify({"error": "Content type must be application/json"}), 400
    
    event_data = request.json
    logger.info("Received Redfish Event:")
    logger.info(json.dumps(event_data, indent=2))
    
    if 'Events' in event_data:
        for event in event_data['Events']:
            process_event(event)
    elif 'EventType' in event_data:
        process_event(event_data)
    else:
        logger.warning("Unknown event format received")
    
    clean_event_cache()
    
    return jsonify({"status": "success", "message": "Event received"}), 200

def process_event(event):
    event_type = event.get('EventType', 'Unknown')
    message_id = event.get('MessageId', event.get('MessageID', 'Unknown'))
    severity = event.get('Severity', 'Unknown')
    message = event.get('Message', 'No message provided')
    origin = event.get('OriginOfCondition', {})
    device_id = event.get('DeviceId', 'Unknown')
    actions = event.get('Actions', [])
    dedup_window = event.get('DeduplicationTimeWindow', 0)
    
    logger.info(f"Event Type: {event_type}")
    logger.info(f"MessageId: {message_id}")
    logger.info(f"Severity: {severity}")
    logger.info(f"Message: {message}")
    logger.info(f"Device ID: {device_id}")
    logger.info(f"Deduplication Window: {dedup_window} seconds")
    logger.info(f"Actions: {', '.join(actions) if actions else 'None'}")
    
    if origin:
        logger.info(f"Origin: {json.dumps(origin, indent=2)}")
    
    if is_duplicate_event(event):
        logger.info(f"Skipping duplicate event from {device_id} (dedup window: {dedup_window}s)")
        return
    
    execute_actions(actions, event)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "up", 
        "service": "Redfish Event Receiver",
        "cache_size": len(event_cache)
    }), 200

@app.route('/cache', methods=['GET'])
def view_cache():
    cache_view = {}
    
    with cache_lock:
        for key, data in event_cache.items():
            cache_view[key] = {
                "timestamp": data["timestamp"].isoformat(),
                "count": data["count"],
                "age_seconds": (datetime.now() - data["timestamp"]).total_seconds()
            }
    
    return jsonify({
        "cache_size": len(cache_view),
        "entries": cache_view
    }), 200

@app.route('/cache/clear', methods=['POST'])
def clear_cache():
    with cache_lock:
        size = len(event_cache)
        event_cache.clear()
    
    return jsonify({
        "status": "success",
        "message": f"Cleared {size} entries from cache"
    }), 200

if __name__ == '__main__':
    try:
        port = 5001
        logger.info(f"Starting Redfish Event Receiver on port {port}")
        logger.info(f"Event endpoint: http://localhost:{port}/events")
        app.run(host='0.0.0.0', port=port, debug=True)
    except Exception as e:
        logger.error(f"Error starting server: {str(e)}")