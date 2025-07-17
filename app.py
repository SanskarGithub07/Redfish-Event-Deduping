import streamlit as st
import os
import io
import sys
import logging
import threading
from simulator_new import run_simulation # Import the refactored function
import subprocess
import time

# --- Configure Streamlit Page ---
st.set_page_config(
    page_title="Redfish Event Simulator & Deduplication",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("Redfish Event Deduplication Project 📈")
st.write("Simulate Redfish events and observe deduplication behavior.")

class StreamlitLogHandler(logging.Handler):
    def __init__(self, placeholder, max_lines=500):
        super().__init__()
        self.placeholder = placeholder
        self.log_messages = []
        self.max_lines = max_lines
        # Set formatter for this handler
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    def emit(self, record):
        msg = self.format(record)
        self.log_messages.append(msg)
        display_messages = self.log_messages[-self.max_lines:]
        self.placeholder.code("\n".join(display_messages))

# --- Sidebar for Global Configuration ---
st.sidebar.header("Global Configuration ⚙️")

emulator_host = st.sidebar.text_input("Emulator Host", value="localhost")
emulator_port = st.sidebar.number_input("Emulator Port", value=5000, min_value=1, max_value=65535)
destination_url = st.sidebar.text_input("Receiver Destination URL", value="http://localhost:5001/events")

st.sidebar.markdown("---")
st.sidebar.header("Simulation Mode Selection 🎯")
simulation_mode = st.sidebar.radio(
    "Choose Simulation Mode",
    ("generic", "device", "all", "mixed", "realistic")
)

st.sidebar.markdown("---")

# --- Main Area for Mode-Specific Parameters ---
st.header("Simulation Parameters 📊")

common_params = {}
if simulation_mode in ["generic", "device", "all"]:
    st.subheader("Common Simulation Settings")
    common_params['delay'] = st.slider("Delay between events (seconds)", min_value=0.1, max_value=10.0, value=2.0, step=0.1)
    common_params['duplicates'] = st.checkbox("Enable Duplicate Events", value=False)
    if common_params['duplicates']:
        common_params['duplicate_count'] = st.number_input("Number of Duplicates per Event", min_value=1, value=3)
        common_params['duplicate_interval'] = st.slider("Interval between Duplicates (seconds)", min_value=0.1, max_value=5.0, value=1.0, step=0.1)
    else:
        common_params['duplicate_count'] = 0 # Not used but good to initialize
        common_params['duplicate_interval'] = 0.0 # Not used but good to initialize

# Placeholder for device config files and generic event files
device_configs_dir = "." # Assumes config_*.json files are in the same directory
generic_events_dir = "." # Assumes events_generic.json is in the same directory

# Function to get available config files
@st.cache_data
def get_config_files():
    return [f for f in os.listdir(device_configs_dir) if f.startswith('config_') and f.endswith('.json')]

@st.cache_data
def get_generic_events_files():
    return [f for f in os.listdir(generic_events_dir) if f == 'events_generic.json']

# Initialize paths for file inputs
config_file_options = [""] + get_config_files()
generic_events_options = [""] + get_generic_events_files()

if simulation_mode == "generic":
    st.subheader("Generic Mode Specifics")
    selected_event_file = st.selectbox("Select Generic Events File", options=generic_events_options, index=generic_events_options.index("events_generic.json") if "events_generic.json" in generic_events_options else 0)
    generic_device_id = st.text_input("Device ID for Generic Events (Optional)", value="GENERIC-DEVICE-001")
    params = {
        **common_params,
        'events': selected_event_file if selected_event_file else None,
        'device_id': generic_device_id
    }

elif simulation_mode == "device":
    st.subheader("Device Specific Mode Specifics")
    selected_config_file = st.selectbox("Select Device Configuration File", options=config_file_options)
    params = {
        **common_params,
        'config': selected_config_file if selected_config_file else None
    }
    if not selected_config_file:
        st.warning("Please select a device configuration file.")

elif simulation_mode == "all":
    st.subheader("All Devices Mode Specifics")
    benchmark_mode = st.checkbox("Enable Benchmark Mode (for 'all' mode)", value=False)
    params = {
        **common_params,
        'benchmark': benchmark_mode
    }

elif simulation_mode == "mixed":
    st.subheader("Mixed Mode Specifics")
    use_all_devices_mixed = st.checkbox("Use events from ALL device configs", value=True)
    if use_all_devices_mixed:
        config_file_mixed = None
        events_file_mixed = None
        device_id_mixed = None
        if not get_config_files():
            st.warning("No device configuration files found. Mixed mode might not have events.")
    else:
        file_source_mixed = st.radio("Select event source for mixed mode", ("Generic Events File", "Single Device Config File"))
        if file_source_mixed == "Generic Events File":
            events_file_mixed = st.selectbox("Select Generic Events File", options=generic_events_options, index=generic_events_options.index("events_generic.json") if "events_generic.json" in generic_events_options else 0, key="mixed_generic_file")
            device_id_mixed = st.text_input("Device ID for Generic Events (Optional, Mixed Mode)", value="MIXED-GENERIC-001")
            config_file_mixed = None
        else: # Single Device Config File
            config_file_mixed = st.selectbox("Select Device Configuration File", options=config_file_options, key="mixed_device_file")
            events_file_mixed = None
            device_id_mixed = None
            if not config_file_mixed:
                st.warning("Please select a device configuration file.")

    batch_size = st.slider("Batch Size", min_value=1, max_value=20, value=5)
    duplicate_probability = st.slider("Duplicate Probability (0.0 - 1.0)", min_value=0.0, max_value=1.0, value=0.3, step=0.05)
    
    st.markdown("##### Duplicate Count Range")
    col1, col2 = st.columns(2)
    with col1:
        duplicate_count_min = st.number_input("Min Duplicates", min_value=1, value=2)
    with col2:
        duplicate_count_max = st.number_input("Max Duplicates", min_value=duplicate_count_min, value=4)

    st.markdown("##### Time Spread Range for Duplicates (seconds)")
    col3, col4 = st.columns(2)
    with col3:
        time_spread_min = st.slider("Min Time Spread", min_value=0.1, max_value=10.0, value=1.0, step=0.1)
    with col4:
        time_spread_max = st.slider("Max Time Spread", min_value=time_spread_min, max_value=20.0, value=5.0, step=0.1)

    num_batches = st.number_input("Number of Batches", min_value=1, value=3)

    st.markdown("##### Batch Interval Range (seconds)")
    col5, col6 = st.columns(2)
    with col5:
        batch_interval_min = st.slider("Min Batch Interval", min_value=1, max_value=60, value=10)
    with col6:
        batch_interval_max = st.slider("Max Batch Interval", min_value=batch_interval_min, max_value=120, value=20)

    params = {
        'events': events_file_mixed,
        'device_id': device_id_mixed,
        'config': config_file_mixed,
        'use_all_devices': use_all_devices_mixed,
        'batch_size': batch_size,
        'duplicate_probability': duplicate_probability,
        'duplicate_count_min': duplicate_count_min,
        'duplicate_count_max': duplicate_count_max,
        'time_spread_min': time_spread_min,
        'time_spread_max': time_spread_max,
        'num_batches': num_batches,
        'batch_interval_min': batch_interval_min,
        'batch_interval_max': batch_interval_max
    }


elif simulation_mode == "realistic":
    st.subheader("Realistic Mode Specifics")
    use_all_devices_realistic = st.checkbox("Use events from ALL device configs", value=True, key="realistic_all_devices")
    if use_all_devices_realistic:
        config_file_realistic = None
        events_file_realistic = None
        device_id_realistic = None
        if not get_config_files():
            st.warning("No device configuration files found. Realistic mode might not have events.")
    else:
        file_source_realistic = st.radio("Select event source for realistic mode", ("Generic Events File", "Single Device Config File"), key="realistic_file_source")
        if file_source_realistic == "Generic Events File":
            events_file_realistic = st.selectbox("Select Generic Events File", options=generic_events_options, index=generic_events_options.index("events_generic.json") if "events_generic.json" in generic_events_options else 0, key="realistic_generic_file")
            device_id_realistic = st.text_input("Device ID for Generic Events (Optional, Realistic Mode)", value="REALISTIC-GENERIC-001")
            config_file_realistic = None
        else: # Single Device Config File
            config_file_realistic = st.selectbox("Select Device Configuration File", options=config_file_options, key="realistic_device_file")
            events_file_realistic = None
            device_id_realistic = None
            if not config_file_realistic:
                st.warning("Please select a device configuration file.")

    scenario_duration = st.number_input("Scenario Duration (seconds)", min_value=30, max_value=3600, value=180)
    
    st.markdown("##### Batch Frequency Range (seconds)")
    col7, col8 = st.columns(2)
    with col7:
        batch_frequency_min = st.slider("Min Batch Frequency", min_value=1, max_value=60, value=8)
    with col8:
        batch_frequency_max = st.slider("Max Batch Frequency", min_value=batch_frequency_min, max_value=120, value=20)
    
    duplicate_probability_realistic = st.slider("Duplicate Probability (0.0 - 1.0)", min_value=0.0, max_value=1.0, value=0.35, step=0.05, key="realistic_dup_prob")

    params = {
        'events': events_file_realistic,
        'device_id': device_id_realistic,
        'config': config_file_realistic,
        'use_all_devices': use_all_devices_realistic,
        'scenario_duration': scenario_duration,
        'batch_frequency_min': batch_frequency_min,
        'batch_frequency_max': batch_frequency_max,
        'duplicate_probability': duplicate_probability_realistic
    }


# --- Execution Section ---
st.markdown("---")
st.header("Run Simulation ▶️")

# Add a placeholder for logs
log_output_placeholder = st.empty()

# Create a custom handler for Streamlit
streamlit_handler = StreamlitLogHandler(log_output_placeholder)

# Add the handler to the root logger (this will capture all logs)
# Ensure only one instance of the handler is active
if not any(isinstance(h, StreamlitLogHandler) for h in logging.getLogger().handlers):
    logging.getLogger().addHandler(streamlit_handler)
logging.getLogger().setLevel(logging.INFO) # Set the root logger level

# Check if required files are selected before enabling the button
can_run = True
if simulation_mode == "device" and not params.get('config'):
    can_run = False
    st.error("Please select a configuration file for 'device' mode.")
if simulation_mode == "generic" and not params.get('events'):
    can_run = False
    st.error("Please select an events file for 'generic' mode.")
if simulation_mode in ["mixed", "realistic"] and not params.get('use_all_devices'):
    if simulation_mode == "mixed" and not (params.get('events') or params.get('config')):
        can_run = False
        st.error("Please select an events file or device config for 'mixed' mode when 'Use all devices' is unchecked.")
    elif simulation_mode == "realistic" and not (params.get('events') or params.get('config')):
        can_run = False
        st.error("Please select an events file or device config for 'realistic' mode when 'Use all devices' is unchecked.")


if st.button("Start Simulation", type="primary", disabled=not can_run):
    # Clear previous logs before starting a new run
    streamlit_handler.log_messages = []
    log_output_placeholder.code("") # Clear the display

    with st.spinner("Running simulation... Please wait and observe logs below."):
        # Pass global parameters as well
        full_params = {
            'mode': simulation_mode,
            'host': emulator_host,
            'port': emulator_port,
            'destination': destination_url,
            **params
        }
        
        # Log the parameters being used
        st.write("---")
        st.write("### Simulation Parameters Being Used:")
        st.json(full_params)
        st.write("---")

        try:
            # The run_simulation function now returns the logs as a string
            # and the simulation result.
            captured_logs, sim_result = run_simulation(**full_params)
            print(captured_logs)
            
            # The StreamlitLogHandler should already be updating the placeholder,
            # but we can ensure the final state is shown and maybe append summary.
            final_log_message = f"\nSimulation finished. Total successful events: {sim_result}"
            streamlit_handler.log_messages.append(final_log_message)
            log_output_placeholder.code("\n".join(streamlit_handler.log_messages[-streamlit_handler.max_lines:])) # Update one last time

            st.success(f"Simulation completed successfully! Total events sent: {sim_result}")
        except Exception as e:
            st.error(f"Simulation failed: {e}")
            # Ensure error message is also in logs
            streamlit_handler.log_messages.append(f"ERROR: Simulation failed: {e}")
            log_output_placeholder.code("\n".join(streamlit_handler.log_messages[-streamlit_handler.max_lines:]))


st.markdown("---")
st.info("Ensure the **Redfish Event Receiver** (`receiver.py`) and a Redfish emulator are running before starting the simulation.")