import json
import logging
import requests
import time
import uuid
import argparse
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RedfishEventSimulator:
    def __init__(self, emulator_host="localhost", emulator_port=5000, events_file="events.json"):
        self.emulator_base_url = f"http://{emulator_host}:{emulator_port}"
        self.events_file = events_file
        self.subscription_id = None
        self.subscription_url = None
        
    def load_events(self):
        try:
            with open(self.events_file, 'r') as f:
                events_data = json.load(f)
            logger.info(f"Loaded {len(events_data)} events from {self.events_file}")
            return events_data
        except Exception as e:
            logger.error(f"Error loading events from {self.events_file}: {str(e)}")
            return []
            
    def create_subscription(self, destination="http://localhost:5001/events"):
        subscription_id = str(uuid.uuid4())[:8]
        
        subscription_payload = {
            "Id": subscription_id,
            "Name": "Event Subscription " + subscription_id,
            "Destination": destination,
            "Context": "Redfish Event Simulator",
            "Protocol": "Redfish",
            "EventTypes": [
                "StatusChange",
                "ResourceUpdated",
                "ResourceAdded",
                "ResourceRemoved",
                "Alert"
            ]
        }
        
        try:
            url = f"{self.emulator_base_url}/redfish/v1/EventService/Subscriptions"
            logger.info(f"Creating subscription to {url}")
            logger.info(f"Destination: {destination}")
            
            response = requests.post(
                url,
                json=subscription_payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code in (200, 201):
                logger.info(f"Subscription created successfully with ID: {subscription_id}")
                self.subscription_id = subscription_id
                self.subscription_url = f"/redfish/v1/EventService/Subscriptions/{subscription_id}"
                return True
            else:
                logger.error(f"Failed to create subscription: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error creating subscription: {str(e)}")
            return False
            
    def send_event(self, event_data):
        try:
            deduplication_time_window = event_data.get("DeduplicationTimeWindow", 0)  
            actions = event_data.get("Actions", [])
            device_id = event_data.get("DeviceId", "Unknown")
            
            test_event_payload = {
                "EventType": event_data.get("EventType", "Alert"),
                "Message": event_data.get("Message", "Test event"),
                "MessageId": event_data.get("MessageId", "Alert.1.0"),
                "OriginOfCondition": event_data.get("OriginOfCondition", {}),
                "Severity": event_data.get("Severity", "OK"),
                "DeduplicationTimeWindow": deduplication_time_window,
                "Actions": actions,
                "DeviceId": device_id
            }
            
            url = f"{self.emulator_base_url}/redfish/v1/EventService/Actions/EventService.SendTestEvent"
            
            logger.info(f"Sending test event to: {url}")
            logger.info(f"Event payload: {json.dumps(test_event_payload, indent=2)}")
            
            response = requests.post(
                url,
                json=test_event_payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code in (200, 201, 202, 204):
                logger.info(f"Event successfully sent via emulator's SendTestEvent action")
                return True
            else:
                logger.warning(f"Failed to send via emulator's SendTestEvent action: {response.status_code} - {response.text}")
                
                logger.info("Falling back to direct delivery")
                
                if not self.subscription_id:
                    logger.error("No active subscription found for fallback delivery")
                    return False
                
                now = datetime.now().isoformat()
                event_id = str(uuid.uuid4())
                
                event_object = {
                    "EventId": event_id,
                    "EventType": event_data.get("EventType", "Alert"),
                    "EventTimestamp": now,
                    "Severity": event_data.get("Severity", "OK"),
                    "Message": event_data.get("Message", ""),
                    "MessageId": event_data.get("MessageId", "Alert.1.0"),
                    "MessageArgs": event_data.get("MessageArgs", []),
                    "OriginOfCondition": event_data.get("OriginOfCondition", {}),
                    "DeduplicationTimeWindow": deduplication_time_window,
                    "Actions": actions,
                    "DeviceId": device_id
                }
                
                event_payload = {
                    "@odata.type": "#Event.v1_3_0.Event",
                    "Id": event_id,
                    "Name": "Redfish Event",
                    "Context": "Redfish Event Simulator",
                    "Events": [event_object]
                }
                
                destination = event_data.get("Destination", "http://localhost:5001/events")
                
                logger.info(f"Sending event directly to: {destination}")
                logger.info(f"Event data: {json.dumps(event_object, indent=2)}")
                
                response = requests.post(
                    destination,
                    json=event_payload,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code == 200:
                    logger.info("Direct event delivery successful")
                    return True
                else:
                    logger.error(f"Failed direct event delivery: {response.status_code} - {response.text}")
                    return False
                
        except Exception as e:
            logger.error(f"Error sending event: {str(e)}")
            return False
    
    def simulate_duplicate_events(self, event_data, count=3, interval=1):
        successful_sends = 0
        
        logger.info(f"Simulating {count} duplicate events with {interval}s interval")
        for i in range(count):
            logger.info(f"Sending duplicate event {i+1}/{count}")
            if self.send_event(event_data):
                successful_sends += 1
            
            if i < count - 1:  
                time.sleep(interval)
                
        return successful_sends
            
    def run_simulation(self, delay=2, destination=None, send_duplicates=False, duplicate_count=3, duplicate_interval=1):
        events = self.load_events()
        if not events:
            logger.error("No events to simulate")
            return 0
            
        successful_events = 0
        
        if not self.create_subscription(destination=destination if destination else "http://localhost:5001/events"):
            logger.error("Failed to create subscription, aborting simulation")
            return 0
            
        logger.info(f"Starting simulation with {len(events)} events")
        for i, event in enumerate(events, 1):
            logger.info(f"Sending event {i}/{len(events)}")
            
            if send_duplicates:
                successful_events += self.simulate_duplicate_events(
                    event,
                    count=duplicate_count,
                    interval=duplicate_interval
                )
            else:
                if self.send_event(event):
                    successful_events += 1
                
            if i < len(events):
                time.sleep(delay)
                
        logger.info(f"Simulation complete. Successfully sent {successful_events} events")
        return successful_events

def main():
    parser = argparse.ArgumentParser(description="Redfish Event Simulator")
    parser.add_argument("--host", default="localhost", help="Redfish emulator host")
    parser.add_argument("--port", type=int, default=5000, help="Redfish emulator port")
    parser.add_argument("--events", default="events.json", help="Path to events JSON file")
    parser.add_argument("--delay", type=int, default=2, help="Delay between events in seconds")
    parser.add_argument("--destination", default="http://localhost:5001/events", 
                        help="Destination URL for events")
    parser.add_argument("--duplicates", action="store_true", 
                        help="Send duplicate events to test deduplication")
    parser.add_argument("--duplicate-count", type=int, default=3, 
                        help="Number of duplicate events to send for each event")
    parser.add_argument("--duplicate-interval", type=float, default=1.0, 
                        help="Time interval between duplicate events in seconds")
    
    args = parser.parse_args()
    
    simulator = RedfishEventSimulator(
        emulator_host=args.host,
        emulator_port=args.port,
        events_file=args.events
    )
    
    simulator.run_simulation(
        delay=args.delay, 
        destination=args.destination,
        send_duplicates=args.duplicates,
        duplicate_count=args.duplicate_count,
        duplicate_interval=args.duplicate_interval
    )

if __name__ == "__main__":
    main()