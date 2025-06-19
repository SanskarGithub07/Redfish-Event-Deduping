import json
import logging
import requests
import time
import uuid
import argparse
import os
import glob
import random
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RedfishEventSimulator:
    def __init__(self, emulator_host="localhost", emulator_port=5000):
        self.emulator_base_url = f"http://{emulator_host}:{emulator_port}"
        self.subscription_id = None
        self.subscription_url = None
        
    def load_generic_events(self, events_file="events_generic.json"):
        try:
            with open(events_file, 'r') as f:
                events_data = json.load(f)
            logger.info(f"Loaded {len(events_data)} generic events from {events_file}")
            return events_data
        except Exception as e:
            logger.error(f"Error loading generic events from {events_file}: {str(e)}")
            return []
    
    def load_device_config(self, config_file):
        try:
            with open(config_file, 'r') as f:
                config_data = json.load(f)
            device_id = config_data.get('device_id', 'Unknown')
            events = config_data.get('events', [])
            logger.info(f"Loaded {len(events)} events for device {device_id} from {config_file}")
            return config_data
        except Exception as e:
            logger.error(f"Error loading device config from {config_file}: {str(e)}")
            return None
    
    def load_all_device_configs(self):
        config_files = glob.glob("config_*.json")
        device_configs = []
        
        for config_file in config_files:
            config = self.load_device_config(config_file)
            if config:
                device_configs.append(config)
        
        logger.info(f"Loaded configurations for {len(device_configs)} devices")
        return device_configs
    
    def get_events_from_config(self, config_data):
        events = []
        device_id = config_data.get('device_id', 'Unknown')
        
        for event in config_data.get('events', []):
            event_copy = event.copy()
            event_copy['DeviceId'] = device_id
            events.append(event_copy)
        
        return events
    
    def get_all_events_from_configs(self, device_configs):
        all_events = []
        
        for config_data in device_configs:
            events = self.get_events_from_config(config_data)
            all_events.extend(events)
        
        logger.info(f"Collected {len(all_events)} events from {len(device_configs)} device configurations")
        return all_events
    
    def prepare_generic_events(self, generic_events, device_id=None):
        prepared_events = []
        
        for event in generic_events:
            event_copy = event.copy()
            if device_id:
                event_copy['DeviceId'] = device_id
            prepared_events.append(event_copy)
        
        return prepared_events

    def load_events_based_on_mode(self, events_file=None, config_file=None, device_id=None, use_all_devices=False):
        events = []
        
        if use_all_devices:
            device_configs = self.load_all_device_configs()
            if device_configs:
                events = self.get_all_events_from_configs(device_configs)
                logger.info(f"Using events from all {len(device_configs)} device configurations")
            else:
                logger.warning("No device configurations found, falling back to generic events")
                if events_file and os.path.exists(events_file):
                    events = self.load_generic_events(events_file)
                    events = self.prepare_generic_events(events, device_id)
        elif config_file:
            config_data = self.load_device_config(config_file)
            if config_data:
                events = self.get_events_from_config(config_data)
                device_name = config_data.get('device_name', config_data.get('device_id', 'Unknown'))
                logger.info(f"Using events from device configuration: {device_name}")
            else:
                logger.error(f"Failed to load device configuration from {config_file}")
        else:
            if events_file and os.path.exists(events_file):
                events = self.load_generic_events(events_file)
                events = self.prepare_generic_events(events, device_id)
                logger.info("Using generic events")
            else:
                logger.error(f"Generic events file not found: {events_file}")
        
        return events
            
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
                "MessageArgs": event_data.get("MessageArgs", []),
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
                
                # if not self.subscription_id:
                #     logger.error("No active subscription found for fallback delivery")
                #     return False
                
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
    
    def create_event_batch(self, events, batch_size=5, duplicate_probability=0.3, 
                          duplicate_count_range=(2, 5), time_spread_range=(0.5, 3.0)):
        batch = []
        
        selected_events = random.choices(events, k=batch_size)
        
        for event in selected_events:
            if random.random() < duplicate_probability:
                duplicate_count = random.randint(*duplicate_count_range)
                time_spread = random.uniform(*time_spread_range)
                
                logger.info(f"Creating {duplicate_count} duplicates of event {event.get('MessageId', 'Unknown')} "
                           f"spread over {time_spread:.1f}s")
                
                for i in range(duplicate_count):
                    if i == 0:
                        delay = 0  
                    else:
                        delay = random.uniform(0.1, time_spread / duplicate_count)
                    
                    batch.append((event.copy(), delay))
            else:
                batch.append((event.copy(), 0))
        
        return batch
    
    def create_realistic_event_scenario(self, events, scenario_duration=300, 
                                      batch_frequency_range=(5, 15), 
                                      duplicate_probability=0.4):
        scenario = []
        current_time = 0
        batch_number = 1
        
        while current_time < scenario_duration:
            batch_size = random.randint(3, 8)  
            batch = self.create_event_batch(
                events, 
                batch_size=batch_size,
                duplicate_probability=duplicate_probability
            )
            
            logger.info(f"Created batch {batch_number} with {len(batch)} events at t={current_time:.1f}s")
            
            batch_start_time = current_time
            cumulative_delay = 0
            
            for event, delay in batch:
                cumulative_delay += delay
                absolute_time = batch_start_time + cumulative_delay
                scenario.append((event, absolute_time))
            
            next_batch_delay = random.uniform(*batch_frequency_range)
            current_time += next_batch_delay
            batch_number += 1
        
        scenario.sort(key=lambda x: x[1])
        
        logger.info(f"Created realistic scenario with {len(scenario)} total events over {scenario_duration}s")
        return scenario
    
    def run_mixed_simulation(self, events_file="events_generic.json", device_id=None,
                           config_file=None, use_all_devices=False,
                           destination=None, batch_size=5, duplicate_probability=0.3,
                           duplicate_count_range=(2, 4), time_spread_range=(1.0, 5.0),
                           num_batches=3, batch_interval_range=(10, 20)):
        
        events = self.load_events_based_on_mode(
            events_file=events_file,
            config_file=config_file,
            device_id=device_id,
            use_all_devices=use_all_devices
        )
        
        if not events:
            logger.error("No events available for mixed simulation")
            return 0
        
        # if not self.create_subscription(destination=destination if destination else "http://localhost:5001/events"):
        #     logger.error("Failed to create subscription, aborting simulation")
        #     return 0
        
        successful_events = 0
        total_events_planned = 0
        
        logger.info(f"Starting mixed simulation with {num_batches} batches")
        logger.info(f"Batch size: {batch_size}, Duplicate probability: {duplicate_probability}")
        logger.info(f"Duplicate count range: {duplicate_count_range}, Time spread range: {time_spread_range}")
        
        for batch_num in range(num_batches):
            logger.info(f"\n--- Starting Batch {batch_num + 1}/{num_batches} ---")
            
            batch = self.create_event_batch(
                events,
                batch_size=batch_size,
                duplicate_probability=duplicate_probability,
                duplicate_count_range=duplicate_count_range,
                time_spread_range=time_spread_range
            )
            
            total_events_planned += len(batch)
            
            batch_start_time = time.time()
            for i, (event, delay) in enumerate(batch):
                if delay > 0:
                    logger.info(f"Waiting {delay:.1f}s before next event in batch...")
                    time.sleep(delay)
                
                device_id_str = event.get('DeviceId', 'Unknown')
                message_id = event.get('MessageId', 'Unknown')
                logger.info(f"Batch {batch_num + 1}, Event {i + 1}/{len(batch)}: "
                           f"Sending {message_id} from {device_id_str}")
                
                if self.send_event(event):
                    successful_events += 1
            
            batch_duration = time.time() - batch_start_time
            logger.info(f"Batch {batch_num + 1} completed in {batch_duration:.1f}s")
            
            if batch_num < num_batches - 1:
                batch_interval = random.uniform(*batch_interval_range)
                logger.info(f"Waiting {batch_interval:.1f}s before next batch...")
                time.sleep(batch_interval)
        
        logger.info(f"\nMixed simulation complete!")
        logger.info(f"Total events planned: {total_events_planned}")
        logger.info(f"Successfully sent: {successful_events}")
        logger.info(f"Success rate: {(successful_events/total_events_planned)*100:.1f}%")
        
        return successful_events
    
    def run_realistic_scenario(self, events_file="events_generic.json", device_id=None,
                             config_file=None, use_all_devices=False,
                             destination=None, scenario_duration=180, 
                             batch_frequency_range=(8, 20), duplicate_probability=0.35):
        
        events = self.load_events_based_on_mode(
            events_file=events_file,
            config_file=config_file,
            device_id=device_id,
            use_all_devices=use_all_devices
        )
        
        if not events:
            logger.error("No events available for realistic scenario")
            return 0
        
        # if not self.create_subscription(destination=destination if destination else "http://localhost:5001/events"):
        #     logger.error("Failed to create subscription, aborting simulation")
        #     return 0
        
        scenario = self.create_realistic_event_scenario(
            events,
            scenario_duration=scenario_duration,
            batch_frequency_range=batch_frequency_range,
            duplicate_probability=duplicate_probability
        )
        
        logger.info(f"Starting realistic scenario simulation")
        logger.info(f"Duration: {scenario_duration}s, Events: {len(scenario)}, "
                   f"Duplicate probability: {duplicate_probability}")
        
        successful_events = 0
        start_time = time.time()
        
        for i, (event, event_time) in enumerate(scenario):
            current_time = time.time() - start_time
            if event_time > current_time:
                wait_time = event_time - current_time
                logger.info(f"Waiting {wait_time:.1f}s until next event...")
                time.sleep(wait_time)
            
            device_id_str = event.get('DeviceId', 'Unknown')
            message_id = event.get('MessageId', 'Unknown')
            elapsed_time = time.time() - start_time
            
            logger.info(f"Event {i + 1}/{len(scenario)} at t={elapsed_time:.1f}s: "
                       f"Sending {message_id} from {device_id_str}")
            
            if self.send_event(event):
                successful_events += 1
        
        total_duration = time.time() - start_time
        logger.info(f"\nRealistic scenario complete!")
        logger.info(f"Total duration: {total_duration:.1f}s")
        logger.info(f"Events sent: {len(scenario)}")
        logger.info(f"Successfully sent: {successful_events}")
        logger.info(f"Success rate: {(successful_events/len(scenario))*100:.1f}%")
        
        return successful_events
    
    def run_generic_simulation(self, events_file="events_generic.json", device_id=None, 
                             delay=2, destination=None, send_duplicates=False, 
                             duplicate_count=3, duplicate_interval=1):
        events = self.load_generic_events(events_file)
        if not events:
            logger.error("No generic events to simulate")
            return 0
        
        events = self.prepare_generic_events(events, device_id)
        
        return self._run_simulation_with_events(
            events, delay, destination, send_duplicates, 
            duplicate_count, duplicate_interval
        )
    
    def run_device_specific_simulation(self, config_file, delay=2, destination=None, 
                                     send_duplicates=False, duplicate_count=3, 
                                     duplicate_interval=1):
        config_data = self.load_device_config(config_file)
        if not config_data:
            logger.error(f"Failed to load device config from {config_file}")
            return 0
        
        events = self.get_events_from_config(config_data)
        if not events:
            logger.error(f"No events found in device config {config_file}")
            return 0
        
        device_name = config_data.get('device_name', config_data.get('device_id', 'Unknown'))
        logger.info(f"Running simulation for device: {device_name}")
        
        return self._run_simulation_with_events(
            events, delay, destination, send_duplicates, 
            duplicate_count, duplicate_interval
        )
    
    def run_all_devices_simulation(self, delay=2, destination=None, send_duplicates=False, 
                                 duplicate_count=3, duplicate_interval=1):
        device_configs = self.load_all_device_configs()
        if not device_configs:
            logger.error("No device configurations found")
            return 0
        
        total_successful = 0
        
        for config_data in device_configs:
            device_name = config_data.get('device_name', config_data.get('device_id', 'Unknown'))
            logger.info(f"Starting simulation for device: {device_name}")
            
            events = self.get_events_from_config(config_data)
            if events:
                successful = self._run_simulation_with_events(
                    events, delay, destination, send_duplicates, 
                    duplicate_count, duplicate_interval
                )
                total_successful += successful
                
                if config_data != device_configs[-1]:
                    logger.info(f"Waiting {delay * 2}s before next device...")
                    time.sleep(delay * 2)
            else:
                logger.warning(f"No events found for device: {device_name}")
        
        logger.info(f"All devices simulation complete. Total successful events: {total_successful}")
        return total_successful
    
    def _run_simulation_with_events(self, events, delay=2, destination=None, 
                                  send_duplicates=False, duplicate_count=3, 
                                  duplicate_interval=1):
        successful_events = 0
        
        # if not self.create_subscription(destination=destination if destination else "http://localhost:5001/events"):
        #     logger.error("Failed to create subscription, aborting simulation")
        #     return 0
            
        logger.info(f"Starting simulation with {len(events)} events")
        for i, event in enumerate(events, 1):
            device_id = event.get('DeviceId', 'Unknown')
            logger.info(f"Sending event {i}/{len(events)} from device {device_id}")
            
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
    parser.add_argument("--mode", choices=["generic", "device", "all", "mixed", "realistic"], default="generic",
                        help="Simulation mode: generic events, specific device, all devices, mixed batches, or realistic scenario")
    parser.add_argument("--events", default="events_generic.json", 
                        help="Path to generic events JSON file")
    parser.add_argument("--config", help="Path to device-specific config file (for device mode)")
    parser.add_argument("--use-all-devices", action="store_true",
                        help="Use events from all device config files (for mixed and realistic modes)")
    parser.add_argument("--device-id", help="Device ID to assign to generic events")
    parser.add_argument("--delay", type=int, default=2, help="Delay between events in seconds")
    parser.add_argument("--destination", default="http://localhost:5001/events", 
                        help="Destination URL for events")
    parser.add_argument("--duplicates", action="store_true", 
                        help="Send duplicate events to test deduplication")
    parser.add_argument("--duplicate-count", type=int, default=3, 
                        help="Number of duplicate events to send for each event")
    parser.add_argument("--duplicate-interval", type=float, default=1.0, 
                        help="Time interval between duplicate events in seconds")
    
    parser.add_argument("--batch-size", type=int, default=5,
                        help="Number of events per batch in mixed mode")
    parser.add_argument("--duplicate-probability", type=float, default=0.3,
                        help="Probability of events being duplicated in mixed mode (0.0 to 1.0)")
    parser.add_argument("--duplicate-count-min", type=int, default=2,
                        help="Minimum number of duplicates for duplicated events")
    parser.add_argument("--duplicate-count-max", type=int, default=4,
                        help="Maximum number of duplicates for duplicated events")
    parser.add_argument("--time-spread-min", type=float, default=1.0,
                        help="Minimum time spread for duplicates in seconds")
    parser.add_argument("--time-spread-max", type=float, default=5.0,
                        help="Maximum time spread for duplicates in seconds")
    parser.add_argument("--num-batches", type=int, default=3,
                        help="Number of batches to send in mixed mode")
    parser.add_argument("--batch-interval-min", type=int, default=10,
                        help="Minimum interval between batches in seconds")
    parser.add_argument("--batch-interval-max", type=int, default=20,
                        help="Maximum interval between batches in seconds")
    
    parser.add_argument("--scenario-duration", type=int, default=180,
                        help="Duration of realistic scenario in seconds")
    parser.add_argument("--batch-frequency-min", type=int, default=8,
                        help="Minimum frequency between batches in realistic mode")
    parser.add_argument("--batch-frequency-max", type=int, default=20,
                        help="Maximum frequency between batches in realistic mode")
    
    args = parser.parse_args()
    
    simulator = RedfishEventSimulator(
        emulator_host=args.host,
        emulator_port=args.port
    )
    
    if args.mode == "generic":
        if not os.path.exists(args.events):
            logger.error(f"Generic events file not found: {args.events}")
            return
        
        simulator.run_generic_simulation(
            events_file=args.events,
            device_id=args.device_id,
            delay=args.delay, 
            destination=args.destination,
            send_duplicates=args.duplicates,
            duplicate_count=args.duplicate_count,
            duplicate_interval=args.duplicate_interval
        )
    
    elif args.mode == "device":
        if not args.config:
            logger.error("Device config file must be specified for device mode")
            return
        
        if not os.path.exists(args.config):
            logger.error(f"Device config file not found: {args.config}")
            return
        
        simulator.run_device_specific_simulation(
            config_file=args.config,
            delay=args.delay,
            destination=args.destination,
            send_duplicates=args.duplicates,
            duplicate_count=args.duplicate_count,
            duplicate_interval=args.duplicate_interval
        )
    
    elif args.mode == "all":
        simulator.run_all_devices_simulation(
            delay=args.delay,
            destination=args.destination,
            send_duplicates=args.duplicates,
            duplicate_count=args.duplicate_count,
            duplicate_interval=args.duplicate_interval
        )
    
    elif args.mode == "mixed":
        if args.use_all_devices:
            device_configs = simulator.load_all_device_configs()
            if not device_configs:
                logger.error("No device configurations found. Cannot use --use-all-devices option.")
                return
        elif args.config:
            if not os.path.exists(args.config):
                logger.error(f"Device config file not found: {args.config}")
                return
        else:
            if not os.path.exists(args.events):
                logger.error(f"Generic events file not found: {args.events}")
                return
        
        simulator.run_mixed_simulation(
            events_file=args.events,
            device_id=args.device_id,
            config_file=args.config,
            use_all_devices=args.use_all_devices,
            destination=args.destination,
            batch_size=args.batch_size,
            duplicate_probability=args.duplicate_probability,
            duplicate_count_range=(args.duplicate_count_min, args.duplicate_count_max),
            time_spread_range=(args.time_spread_min, args.time_spread_max),
            num_batches=args.num_batches,
            batch_interval_range=(args.batch_interval_min, args.batch_interval_max)
        )
    
    elif args.mode == "realistic":
        if args.use_all_devices:
            device_configs = simulator.load_all_device_configs()
            if not device_configs:
                logger.error("No device configurations found. Cannot use --use-all-devices option.")
                return
        elif args.config:
            if not os.path.exists(args.config):
                logger.error(f"Device config file not found: {args.config}")
                return
        else:
            if not os.path.exists(args.events):
                logger.error(f"Generic events file not found: {args.events}")
                return
        
        simulator.run_realistic_scenario(
            events_file=args.events,
            device_id=args.device_id,
            config_file=args.config,
            use_all_devices=args.use_all_devices,
            destination=args.destination,
            scenario_duration=args.scenario_duration,
            batch_frequency_range=(args.batch_frequency_min, args.batch_frequency_max),
            duplicate_probability=args.duplicate_probability
        )

if __name__ == "__main__":
    main()