#!/usr/bin/env python3
# Aurora Inverter Monitor - Advanced Client
# Converted from C# to Python

import socket
import struct
import time
import sys
import datetime
import signal
import asyncio
from typing import Tuple

class AuroraClient:
    # Aurora protocol constants
    CMD_GET_DSP = 59
    CMD_GET_CE = 78
    DSP_GRID_VOLTS = 1
    DSP_OUTPUT_POWER = 3
    DSP_PEAK_TODAY = 35
    DSP_TEMPERATURE_1 = 21
    DSP_TEMPERATURE_2 = 22
    DSP_VOLTAGE_1 = 23
    DSP_CURRENT_1 = 25
    DSP_VOLTAGE_2 = 26
    DSP_CURRENT_2 = 27

    def __init__(self, host: str, port: int, timeout: int = 400):
        """Initialize the Aurora client with the given host and port."""
        self.host = host
        self.port = port
        self.timeout = timeout / 1000  # Convert to seconds
        self.socket = None
        self.running = False
        
    async def connect(self):
        """Connect to the Aurora inverter."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.host, self.port))
            print(f"Connected successfully to {self.host}:{self.port}")
            return True
        except Exception as ex:
            print(f"Failed to connect to inverter: {ex}")
            self.close()
            return False

    def close(self):
        """Close the connection to the inverter."""
        if self.socket:
            self.socket.close()
            self.socket = None

    async def start_monitoring(self):
        """Start monitoring the inverter data."""
        if not self.socket and not await self.connect():
            return

        self.running = True
        
        # Set up signal handling for graceful exit
        def signal_handler(sig, frame):
            print("\nStopping monitoring...")
            self.running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        
        print("Press Ctrl+C to exit\n")
        
        try:
            while self.running:
                await self.display_inverter_data()
                await asyncio.sleep(5)  # Update every 5 seconds
        except Exception as ex:
            print(f"Error in monitoring loop: {ex}")
        finally:
            print("\nMonitoring stopped")
            self.close()

    async def display_inverter_data(self):
        """Display the current inverter data."""
        try:
            # Read all important values
            power_output = await self.send_dsp_command(2, self.DSP_OUTPUT_POWER)
            voltage1 = await self.send_dsp_command(2, self.DSP_VOLTAGE_1)
            current1 = await self.send_dsp_command(2, self.DSP_CURRENT_1)
            voltage2 = await self.send_dsp_command(2, self.DSP_VOLTAGE_2)
            current2 = await self.send_dsp_command(2, self.DSP_CURRENT_2)
            temperature = await self.send_dsp_command(2, self.DSP_TEMPERATURE_1)
            temperature2 = await self.send_dsp_command(2, self.DSP_TEMPERATURE_2)
            grid_voltage = await self.send_dsp_command(2, self.DSP_GRID_VOLTS)
            peak_today = await self.send_dsp_command(2, self.DSP_PEAK_TODAY)
            
            # Get energy readings
            energy_today = await self.send_ce_command(2, 0) / 1000.0
            energy_week = await self.send_ce_command(2, 1) / 1000.0
            energy_month = await self.send_ce_command(2, 3) / 1000.0
            energy_year = await self.send_ce_command(2, 4) / 1000.0
            energy_total = await self.send_ce_command(2, 5) / 1000.0
            
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Display the data
            print(f"{now} - Aurora Inverter Status")
            print(f"Power Output:  {power_output:.1f} W")
            print(f"Input 1:       {voltage1:.1f} V, {current1:.2f} A, {voltage1 * current1:.1f} W")
            print(f"Input 2:       {voltage2:.1f} V, {current2:.2f} A, {voltage2 * current2:.1f} W")
            print(f"Temperature:   {temperature:.1f}°C")
            print(f"Grid Voltage:  {grid_voltage:.1f} V")
            
            # Calculate efficiency if possible
            input_power = (voltage1 * current1) + (voltage2 * current2)
            if input_power > 0:
                efficiency = (power_output / input_power) * 100
                print(f"Efficiency:    {efficiency:.1f}%")
            else:
                print("Efficiency:    N/A")
            
            print(f"Peak Today:    {peak_today:.1f} W")
            print(f"Energy Today:  {energy_today:.2f} kWh")
            print(f"Energy Week:   {energy_week:.2f} kWh")
            print(f"Energy Month:  {energy_month:.2f} kWh")
            print(f"Energy Year:   {energy_year:.2f} kWh")
            print(f"Energy Total:  {energy_total:.2f} kWh")
            print()
            
        except Exception as ex:
            print(f"Error getting inverter data: {ex}")

    async def send_command(self, address: int, command: int, data: Tuple[int, int] = (0, 0)) -> bytes:
        """Send a command to the inverter and return the response."""
        if not self.socket:
            if not await self.connect():
                return b''
        
        # Create the command packet
        packet = bytearray(10)
        packet[0] = address  # Inverter address
        packet[1] = command  # Command
        packet[2] = data[0]  # First data byte
        packet[3] = data[1]  # Second data byte
        
        # Calculate the checksum
        checksum = 0
        for i in range(8):
            checksum += packet[i]
        
        # Add the checksum to the packet
        packet[8] = checksum & 0xFF
        packet[9] = (checksum >> 8) & 0xFF
        
        try:
            # Send the packet
            self.socket.send(packet)
            
            # Wait for response
            response = self.socket.recv(10)
            if len(response) != 10:
                print(f"Invalid response length: {len(response)}")
                return b''
            
            # Validate the response
            resp_checksum = response[8] + (response[9] << 8)
            calc_checksum = 0
            for i in range(8):
                calc_checksum += response[i]
            
            if resp_checksum != calc_checksum:
                print(f"Invalid response checksum: {resp_checksum} != {calc_checksum}")
                return b''
            
            return response
        except Exception as ex:
            print(f"Error sending command: {ex}")
            self.close()
            return b''

    async def send_dsp_command(self, address: int, param: int) -> float:
        """Send a DSP command to the inverter and return the response as a float."""
        response = await self.send_command(address, self.CMD_GET_DSP, (param, 0))
        if not response:
            return 0.0
        
        # Extract the value from the response
        value_raw = (response[6] + (response[7] << 8))
        
        # Special conversions based on parameter
        if param == self.DSP_GRID_VOLTS:
            return value_raw * 0.1  # V
        elif param == self.DSP_OUTPUT_POWER:
            return value_raw  # W
        elif param in [self.DSP_TEMPERATURE_1, self.DSP_TEMPERATURE_2]:
            return value_raw * 0.1  # °C
        elif param in [self.DSP_VOLTAGE_1, self.DSP_VOLTAGE_2]:
            return value_raw * 0.1  # V
        elif param in [self.DSP_CURRENT_1, self.DSP_CURRENT_2]:
            return value_raw * 0.01  # A
        elif param == self.DSP_PEAK_TODAY:
            return value_raw  # W
        else:
            return float(value_raw)

    async def send_ce_command(self, address: int, param: int) -> int:
        """Send a Cumulated Energy command to the inverter and return the response as an integer."""
        response = await self.send_command(address, self.CMD_GET_CE, (param, 0))
        if not response:
            return 0
        
        # Energy values are 4-byte values split across the response
        offset = 4
        buffer = response
        bytes_array = bytearray(4)
        bytes_array[0] = buffer[offset + 1]
        bytes_array[1] = buffer[offset + 0]
        bytes_array[2] = buffer[offset + 3]
        bytes_array[3] = buffer[offset]
        
        return struct.unpack('<i', bytes_array)[0]


async def main():
    """Main function to run the Aurora client."""
    print("Aurora Inverter Monitor - Advanced Client")
    print("=========================================")
    
    host = "192.168.1.100"
    port = 8899
    
    # Parse command line arguments if provided
    if len(sys.argv) >= 2:
        host = sys.argv[1]
    if len(sys.argv) >= 3:
        try:
            port = int(sys.argv[2])
        except ValueError:
            print(f"Invalid port number: {sys.argv[2]}")
            sys.exit(1)
    
    client = AuroraClient(host, port)
    await client.start_monitoring()

# Helper methods for external applications
async def get_output_power(client):
    """Get the current output power from the inverter."""
    return await client.send_dsp_command(2, client.DSP_OUTPUT_POWER)

async def get_input_voltage(client, input_num):
    """Get the input voltage from the inverter."""
    if input_num == 1:
        return await client.send_dsp_command(2, client.DSP_VOLTAGE_1)
    else:
        return await client.send_dsp_command(2, client.DSP_VOLTAGE_2)

async def get_input_current(client, input_num):
    """Get the input current from the inverter."""
    if input_num == 1:
        return await client.send_dsp_command(2, client.DSP_CURRENT_1)
    else:
        return await client.send_dsp_command(2, client.DSP_CURRENT_2)

async def get_temperature(client):
    """Get the temperature from the inverter."""
    return await client.send_dsp_command(2, client.DSP_TEMPERATURE_1)

async def get_grid_voltage(client):
    """Get the grid voltage from the inverter."""
    return await client.send_dsp_command(2, client.DSP_GRID_VOLTS)

async def get_energy_today(client):
    """Get the energy produced today from the inverter."""
    return await client.send_ce_command(2, 0) / 1000.0

async def get_energy_week(client):
    """Get the energy produced this week from the inverter."""
    return await client.send_ce_command(2, 1) / 1000.0

async def get_energy_month(client):
    """Get the energy produced this month from the inverter."""
    return await client.send_ce_command(2, 3) / 1000.0

async def get_energy_year(client):
    """Get the energy produced this year from the inverter."""
    return await client.send_ce_command(2, 4) / 1000.0

async def get_energy_total(client):
    """Get the total energy produced from the inverter."""
    return await client.send_ce_command(2, 5) / 1000.0

async def get_peak_power_today(client):
    """Get the peak power produced today from the inverter."""
    return await client.send_dsp_command(2, client.DSP_PEAK_TODAY)

if __name__ == "__main__":
    asyncio.run(main())