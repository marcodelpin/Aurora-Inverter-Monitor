#!/usr/bin/env python3
# Aurora Inverter Monitor - Web Application

import asyncio
import datetime
import json
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
from typing import Dict, List, Any, Optional

from flask import Flask, render_template, jsonify, request

# Import our Aurora client
from aurora_client import AuroraClient

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("aurora_web")

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key')

# Config file path
config_file = os.environ.get('CONFIG_FILE', 'aurora_config.json')

# Default configuration
default_config = {
    'inverter_host': os.environ.get('INVERTER_HOST', '192.168.1.100'),
    'inverter_port': int(os.environ.get('INVERTER_PORT', '8899')),
    'polling_interval': int(os.environ.get('POLLING_INTERVAL', '300')),
    'ui_refresh_interval': 30,
    'chart_refresh_interval': 300,
    'web_host': os.environ.get('WEB_HOST', '0.0.0.0'),
    'web_port': int(os.environ.get('WEB_PORT', '5000')),
    'timezone': os.environ.get('TZ', 'Europe/Rome'),
    'db_path': os.environ.get('DB_PATH', 'aurora_data.db')
}

# Current configuration
config = default_config.copy()

# Global variables
db_path = config['db_path']
inverter_host = config['inverter_host']
inverter_port = config['inverter_port']
polling_interval = config['polling_interval']
last_reading = {}
monitoring_thread = None
stop_event = threading.Event()

# Load configuration from file
def load_config():
    """Load configuration from JSON file."""
    global config, db_path, inverter_host, inverter_port, polling_interval
    
    try:
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                saved_config = json.load(f)
                config.update(saved_config)
        else:
            # Save default config if file doesn't exist
            save_config()
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
    
    # Update global variables
    db_path = config['db_path']
    inverter_host = config['inverter_host']
    inverter_port = config['inverter_port']
    polling_interval = config['polling_interval']
    
    logger.info(f"Configuration loaded: inverter={inverter_host}:{inverter_port}, polling={polling_interval}s")

# Save configuration to file
def save_config():
    """Save configuration to JSON file."""
    try:
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=4)
        logger.info("Configuration saved")
        return True
    except Exception as e:
        logger.error(f"Error saving configuration: {e}")
        return False

# Initialize database
def init_db():
    """Initialize the SQLite database."""
    logger.info(f"Initializing database at {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create readings table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            power_output REAL,
            voltage_1 REAL,
            current_1 REAL,
            voltage_2 REAL,
            current_2 REAL,
            temperature REAL,
            grid_voltage REAL,
            efficiency REAL,
            peak_today REAL,
            energy_today REAL,
            energy_week REAL,
            energy_month REAL,
            energy_year REAL,
            energy_total REAL
        )
        ''')
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return False

# Store data in the database
def store_reading(data: Dict[str, Any]):
    """Store a reading in the database."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get current timestamp
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Insert data
        cursor.execute('''
        INSERT INTO readings (
            timestamp, power_output, voltage_1, current_1, 
            voltage_2, current_2, temperature, grid_voltage,
            efficiency, peak_today, energy_today, energy_week,
            energy_month, energy_year, energy_total
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            timestamp,
            data.get('power_output', 0),
            data.get('voltage_1', 0),
            data.get('current_1', 0),
            data.get('voltage_2', 0),
            data.get('current_2', 0),
            data.get('temperature', 0),
            data.get('grid_voltage', 0),
            data.get('efficiency', 0),
            data.get('peak_today', 0),
            data.get('energy_today', 0),
            data.get('energy_week', 0),
            data.get('energy_month', 0),
            data.get('energy_year', 0),
            data.get('energy_total', 0)
        ))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error storing data in database: {e}")
        return False

# Get readings from database
def get_readings(hours: int = 24) -> List[Dict[str, Any]]:
    """Get readings from the database for the specified time period."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Calculate start time
        start_time = (datetime.datetime.now() - datetime.timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
        
        # Query data
        cursor.execute('''
        SELECT * FROM readings 
        WHERE timestamp >= ? 
        ORDER BY timestamp ASC
        ''', (start_time,))
        
        rows = cursor.fetchall()
        conn.close()
        
        # Convert to list of dicts
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error retrieving data from database: {e}")
        return []

# Async function to poll inverter
async def poll_inverter():
    """Poll the inverter for data at regular intervals."""
    global last_reading
    
    # Initialize client
    client = AuroraClient(inverter_host, inverter_port)
    
    while not stop_event.is_set():
        try:
            # Connect to inverter
            if await client.connect():
                # Get data
                power_output = await client.get_output_power()
                voltage1 = await client.get_input_voltage(1)
                current1 = await client.get_input_current(1)
                voltage2 = await client.get_input_voltage(2)
                current2 = await client.get_input_current(2)
                temperature = await client.get_temperature()
                grid_voltage = await client.get_grid_voltage()
                energy_today = await client.get_energy_today()
                energy_week = await client.get_energy_week()
                energy_month = await client.get_energy_month()
                energy_year = await client.get_energy_year()
                energy_total = await client.get_energy_total()
                peak_today = await client.get_peak_power_today()
                
                # Calculate efficiency if possible
                efficiency = 0
                input_power1 = voltage1 * current1
                input_power2 = voltage2 * current2
                total_input = input_power1 + input_power2
                
                if total_input > 0:
                    efficiency = (power_output / total_input) * 100
                
                # Create data structure
                data = {
                    'power_output': power_output,
                    'voltage_1': voltage1,
                    'current_1': current1,
                    'voltage_2': voltage2,
                    'current_2': current2,
                    'temperature': temperature,
                    'grid_voltage': grid_voltage,
                    'efficiency': efficiency,
                    'peak_today': peak_today,
                    'energy_today': energy_today,
                    'energy_week': energy_week,
                    'energy_month': energy_month,
                    'energy_year': energy_year,
                    'energy_total': energy_total,
                    'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                # Store data
                last_reading = data
                store_reading(data)
                
                logger.info(f"Inverter data updated: {power_output:.2f}W, Efficiency: {efficiency:.1f}%, Today: {energy_today:.2f}kWh")
                
                # Close connection
                client.close()
            else:
                logger.warning("Failed to connect to inverter")
        except Exception as e:
            logger.error(f"Error polling inverter: {e}")
            client.close()
        
        # Wait for next polling interval
        await asyncio.sleep(polling_interval)

# Start monitoring thread
def start_monitoring():
    """Start the monitoring thread."""
    global monitoring_thread, stop_event
    
    # Set up event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Reset stop event
    stop_event.clear()
    
    # Define thread function
    def run_monitoring():
        loop.run_until_complete(poll_inverter())
    
    # Start thread
    monitoring_thread = threading.Thread(target=run_monitoring)
    monitoring_thread.daemon = True
    monitoring_thread.start()
    
    logger.info("Monitoring thread started")

# Stop monitoring thread
def stop_monitoring():
    """Stop the monitoring thread."""
    global monitoring_thread, stop_event
    
    if monitoring_thread and monitoring_thread.is_alive():
        stop_event.set()
        monitoring_thread.join(timeout=5)
        logger.info("Monitoring thread stopped")
    
    monitoring_thread = None

# Routes
@app.route('/')
def index():
    """Render the main dashboard."""
    return render_template('index.html', 
                           config=config, 
                           last_reading=last_reading)

@app.route('/setup')
def setup():
    """Render the setup page."""
    return render_template('setup.html', config=config)

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """API endpoint to get or update configuration."""
    global config
    
    if request.method == 'POST':
        # Update configuration
        try:
            data = request.json
            
            # Update configuration
            for key in data:
                if key in config:
                    # Type conversion for numeric values
                    if key in ['inverter_port', 'web_port', 'polling_interval', 'ui_refresh_interval', 'chart_refresh_interval']:
                        config[key] = int(data[key])
                    else:
                        config[key] = data[key]
            
            # Save configuration
            if save_config():
                # Reload configuration
                load_config()
                
                # Restart monitoring if needed
                if monitoring_thread and monitoring_thread.is_alive():
                    stop_monitoring()
                    start_monitoring()
                
                return jsonify({'status': 'success', 'message': 'Configuration updated successfully'})
            else:
                return jsonify({'status': 'error', 'message': 'Failed to save configuration'})
        except Exception as e:
            logger.error(f"Error updating configuration: {e}")
            return jsonify({'status': 'error', 'message': f'Error updating configuration: {e}'})
    else:
        # Return current configuration
        return jsonify(config)

@app.route('/api/data')
def api_data():
    """API endpoint to get current data."""
    return jsonify(last_reading)

@app.route('/api/history')
def api_history():
    """API endpoint to get historical data."""
    try:
        # Get hours parameter
        hours = request.args.get('hours', default=24, type=int)
        
        # Get readings
        readings = get_readings(hours)
        
        return jsonify(readings)
    except Exception as e:
        logger.error(f"Error retrieving history: {e}")
        return jsonify({'status': 'error', 'message': f'Error retrieving history: {e}'})

# Initialize and start
def main():
    """Main function to initialize and start the application."""
    # Load configuration
    load_config()
    
    # Initialize database
    init_db()
    
    # Start monitoring
    start_monitoring()
    
    # Set up signal handlers
    def signal_handler(sig, frame):
        logger.info("Shutting down...")
        stop_monitoring()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start web server
    logger.info(f"Starting web server on {config['web_host']}:{config['web_port']}")
    app.run(host=config['web_host'], port=config['web_port'], debug=False)

if __name__ == '__main__':
    main()