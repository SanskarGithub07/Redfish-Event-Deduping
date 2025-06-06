import json
import logging
import time
import os
import glob
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
device_configs = {}
configs_lock = threading.Lock()

def load_device_configs():
    global device_configs
    
    config_files = glob.glob("config_*.json")
    
    with configs_lock:
        device_configs = {}
        for config_file in config_files:
            try:
                with open(config_file, 'r') as f:
                    config_data = json.load(f)
                    device_id = config_data.get('device_id')
                    if device_id:
                        device_configs[device_id] = config_data
                        logger.info(f"Loaded config for device: {device_id} from {config_file}")
                    else:
                        logger.warning(f"No device_id found in config file: {config_file}")
            except Exception as e:
                logger.error(f"Error loading config file {config_file}: {str(e)}")
    
    logger.info(f"Loaded configurations for {len(device_configs)} devices")
    return len(device_configs)

def get_device_config(device_id):
    with configs_lock:
        return device_configs.get(device_id)

def get_deduplication_window(event, device_config=None):
    if 'DeduplicationTimeWindow' in event:
        return event['DeduplicationTimeWindow']
    
    if device_config and 'default_deduplication_window' in device_config:
        return device_config['default_deduplication_window']
    
    return 0

def get_event_actions(event, device_config=None):
    """Get actions for an event, considering device-specific config"""
    if 'Actions' in event:
        return event['Actions']
    
    if device_config and 'events' in device_config:
        message_id = event.get('MessageId', event.get('MessageID', ''))
        event_type = event.get('EventType', '')
        
        for config_event in device_config['events']:
            if (config_event.get('MessageId') == message_id and 
                config_event.get('EventType') == event_type):
                return config_event.get('Actions', [])
    
    return []

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

def is_duplicate_event(event, device_config=None):
    dedup_window = get_deduplication_window(event, device_config)
    
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
                logger.info(f"Duplicate event detected for device {event.get('DeviceId', 'Unknown')}. Count: {last_event['count']}")
                return True
        
        event_cache[event_key] = {
            "timestamp": current_time,
            "count": 1,
            "device_id": event.get('DeviceId', 'Unknown')
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

def execute_actions(actions, event_data, device_config=None):
    if not actions:
        logger.info("No actions specified for this event")
        return
    
    device_id = event_data.get('DeviceId', 'Unknown')
    device_name = device_config.get('device_name', device_id) if device_config else device_id
    
    logger.info(f"Executing actions for device {device_name}: {', '.join(actions)}")
    
    for action in actions:
        if action == "NotifyAdmin":
            logger.info(f"ACTION: Would notify admin about {event_data.get('Message', 'an event')} on device {device_name}")
        elif action == "NotifyNetworkAdmin":
            logger.info(f"ACTION: Would notify network admin about {event_data.get('Message', 'an event')} on device {device_name}")
        elif action == "ShutdownServer":
            logger.info(f"ACTION: Would initiate shutdown for device {device_name}")
        elif action == "LogChange":
            logger.info(f"ACTION: Would log change to event database for device {device_name}")
        elif action == "LogError":
            logger.info(f"ACTION: Would log error to system log for device {device_name}")
        elif action == "LogPerformance":
            logger.info(f"ACTION: Would log performance metrics for device {device_name}")
        elif action == "LogUpdate":
            logger.info(f"ACTION: Would log update information for device {device_name}")
        elif action == "MonitorTemperature":
            logger.info(f"ACTION: Would increase temperature monitoring frequency for device {device_name}")
        elif action == "MonitorCPU":
            logger.info(f"ACTION: Would increase CPU monitoring frequency for device {device_name}")
        elif action == "InitializeDrive":
            logger.info(f"ACTION: Would initialize drive at {event_data.get('OriginOfCondition', {}).get('@odata.id', 'Unknown')} on device {device_name}")
        elif action == "UpdateInventory":
            logger.info(f"ACTION: Would update inventory database for device {device_name}")
        elif action == "UpdateNetworkStatus":
            logger.info(f"ACTION: Would update network status for device {device_name}")
        elif action == "CheckPowerSupplies":
            logger.info(f"ACTION: Would schedule power supply diagnostics for device {device_name}")
        elif action == "CheckCabling":
            logger.info(f"ACTION: Would schedule cable diagnostics for device {device_name}")
        elif action == "RerouteTraffic":
            logger.info(f"ACTION: Would reroute network traffic for device {device_name}")
        else:
            logger.info(f"ACTION: Unknown action '{action}' for device {device_name}")

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
    
    device_config = get_device_config(device_id)
    
    dedup_window = get_deduplication_window(event, device_config)
    actions = get_event_actions(event, device_config)
    
    logger.info(f"Event Type: {event_type}")
    logger.info(f"MessageId: {message_id}")
    logger.info(f"Severity: {severity}")
    logger.info(f"Message: {message}")
    logger.info(f"Device ID: {device_id}")
    logger.info(f"Deduplication Window: {dedup_window} seconds")
    logger.info(f"Actions: {', '.join(actions) if actions else 'None'}")
    
    if device_config:
        logger.info(f"Device Name: {device_config.get('device_name', 'Unknown')}")
        logger.info(f"Device Type: {device_config.get('device_type', 'Unknown')}")
        logger.info(f"Location: {device_config.get('location', 'Unknown')}")
    else:
        logger.warning(f"No configuration found for device: {device_id}")
    
    if origin:
        logger.info(f"Origin: {json.dumps(origin, indent=2)}")
    
    if is_duplicate_event(event, device_config):
        logger.info(f"Skipping duplicate event from {device_id} (dedup window: {dedup_window}s)")
        return
    
    execute_actions(actions, event, device_config)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "up", 
        "service": "Redfish Event Receiver",
        "cache_size": len(event_cache),
        "configured_devices": len(device_configs)
    }), 200

@app.route('/devices', methods=['GET'])
def list_devices():
    devices_info = {}
    
    with configs_lock:
        for device_id, config in device_configs.items():
            devices_info[device_id] = {
                "device_name": config.get('device_name', 'Unknown'),
                "device_type": config.get('device_type', 'Unknown'),
                "location": config.get('location', 'Unknown'),
                "default_deduplication_window": config.get('default_deduplication_window', 0),
                "event_count": len(config.get('events', []))
            }
    
    return jsonify({
        "total_devices": len(devices_info),
        "devices": devices_info
    }), 200

@app.route('/devices/<device_id>', methods=['GET'])
def get_device_info(device_id):
    """Get information about a specific device"""
    device_config = get_device_config(device_id)
    
    if not device_config:
        return jsonify({"error": f"Device '{device_id}' not found"}), 404
    
    return jsonify(device_config), 200

@app.route('/cache', methods=['GET'])
def view_cache():
    cache_view = {}
    
    with cache_lock:
        for key, data in event_cache.items():
            cache_view[key] = {
                "timestamp": data["timestamp"].isoformat(),
                "count": data["count"],
                "device_id": data.get("device_id", "Unknown"),
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

@app.route('/configs/reload', methods=['POST'])
def reload_configs():
    try:
        count = load_device_configs()
        return jsonify({
            "status": "success",
            "message": f"Reloaded configurations for {count} devices"
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to reload configs: {str(e)}"
        }), 500

if __name__ == '__main__':
    try:
        load_device_configs()
        
        port = 5001
        logger.info(f"Starting Redfish Event Receiver on port {port}")
        logger.info(f"Event endpoint: http://localhost:{port}/events")
        logger.info(f"Health check: http://localhost:{port}/health")
        logger.info(f"Device list: http://localhost:{port}/devices")
        app.run(host='0.0.0.0', port=port, debug=True)
    except Exception as e:
        logger.error(f"Error starting server: {str(e)}")