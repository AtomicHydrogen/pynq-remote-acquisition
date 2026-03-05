import yaml
import os
import warnings
import pandas as pd
import numpy as np
from pynq import PL, Overlay
from pynq import allocate
from pynq import DefaultIP
import time
import shutil
from time import sleep


try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

# Load YAML file
if __name__ == '__main__':
    with open("test.yaml", 'r') as stream:
        dictionary = yaml.safe_load(stream)

foldername = "outputs_test"
if os.path.exists(foldername):
    shutil.rmtree(foldername)
    print(f"Deleted existing folder: {foldername}")

# Defining detector commands
_command_valids = [0xE0,0xE1,0xE2,0xE3,0xE4,0xE5,0xE6,0xE7,0xE8,0xE9,0x9D,0x9E,0x86,0xA3,0x96,0x9A,0x02,0x85,0x05,0x8C,0x21,0xA1,0x1F,0x9F,0x20,0xA0,0x81,0x01,0x32,0xB2,0x34,0xB4,0x07,0x87,0x0B,0x8B,0x03,0x83,0x84,0x04,0xCB,0x10,0x90,0x48,0xC8,0x4A,0xCA]
_command_has_reply = [0xE0,0x9D,0x9E,0x86,0xA3,0x96,0x9A,0xA1,0x9F,0xA0,0xB2,0xB4,0x87,0x8B,0xC8,0x83,0x84,0xCB]
_command_has_data = [0x21,0x1F,0x20,0x32,0x07,0x0B,0x48,0x03,0x04]
_command_map = {"READ_PART_BASE": 0xE0,
                    "READ_SERIAL_LSB": 0x9D,
                    "READ_SERIAL_MSB": 0x9E,
                    "READ_FIRMWARE_VERSION": 0x86,
                    "READ_MODULE_VERSION": 0xA3,
                    "READ_STATUS": 0x96,
                    "READ_TEMPERATURE": 0x9A,
                    "BREAK": 0x02,
                    "EVENT_ON": 0x85,
                    "EVENT_OFF": 0x05,
                    "FIFO_CLEAR": 0x8C,
                    "SET_THRESHOLD": 0x21,
                    "GET_THRESHOLD": 0xA1,
                    "SET_GPIO": 0x1F,
                    "GET_GPIO": 0x9F,
                    "SET_CLOCK": 0x20,
                    "GET_CLOCK": 0xA0,
                    "RESTORE_SETUP": 0x81,
                    "UPDATE_SETUP": 0x01,
                    "SET_PEAKING_TIME": 0x32,
                    "GET_PEAKING_TIME": 0xB2,
                    "RUN_SELF_TEST": 0x34,
                    "GET_SELF_TEST_RESULTS": 0xB4,
                    "SET_CHANNEL": 0x07,
                    "GET_CHANNEL": 0x87,
                    "CHANNEL_CONTROL": 0x0B,
                    "CHANNEL_STATUS": 0x8B,
                    "SET_ADDR_POINTER": 0x03,
                    "GET_ADDR_POINTER": 0x83,
                    "READ_RAM": 0x84,
                    "WRITE_RAM": 0x04,
                    "EEPROM_CHECKSUM": 0xCB,
                    "HOLD_ON": 0x10,
                    "HOLD_OFF": 0x90,
                    "SET_EMULATOR": 0x48,
                    "GET_EMULATOR": 0xC8,
                    "WRITE_PROTECT_OFF": 0x4A,
                    "WRITE_PROTECT_ON": 0xCA
                   }

# Abstracting the commands
class CZTDriver(DefaultIP):
    """Class for interacting with the AXI CZT Controller version 1.

    Revision: 1.0.24

    This class provides driver support for "user.org:user:AXI_CZT_Controller:1.0".

    The driver has various functions and properties to abstract away the
    funtionality of the register as well as providing translation between
    command names and actual command op codes.

    The driver also wraps an MMIO device for direct access to the underlying
    registers with "read(addr)" and "write(addr,data)" functions.
    """

    def __init__(self, description):
        super().__init__(description=description)
        self.is_channel_disabled = [0]*256
        self.disabled_channel_list = []
        self.num_disabled = 0

    bindto = ['user.org:user:AXI_CZT_Controller:1.0']


    # Register 0 (Offset 0)
    #   [7:0] Command
    #   [8] Valid
    #   [31:16] Data In
    # Register 1 (Offset 4)
    #   [0] Command Done
    #   [8] Reply Valid
    #   [31:16] Reply Data

    def command(self, com, inp = None, timeout = 5000):
        # Bring down command valid in anticipation of new command
        self.write(0x0,0x0000)

        # Check if command is valid
        if type(com) is str:
            if com in _command_map:
                com = _command_map[com]
            else:
                raise ValueError("Invalid Command String")
        if com not in _command_valids:
            raise ValueError("Invalid Command Number")

        # If command needs to send data then,
        #   verify data input is given
        #   send the command along with data and block for acknoledgement
        if (com in _command_has_data):
            if (inp == None):
                raise ValueError(f"Input needed for 0x{com:02x}")
            else:
                # Implement command with data
                packed_command = com | 1<<8 | inp<<16
                self.write(0x0, packed_command)
                rd = self.read(0x4)
                while((not(rd and 0x1)) and timeout!=0):
                    rd = self.read(0x4)
                    timeout -= 1
                if timeout == 0:
                    return -1
                return None

        # If command does not have data then just send the command
        packed_command = com | 1<<8 | 0xffff0000
        self.write(0x00, packed_command)

        # Wait for acknoledgement of successful command transmission
        rd = self.read(0x04)
        while((not(rd and 0x0001)) and timeout!=0):
            rd = self.read(0x04)
            timeout -= 1
        if timeout == 0:
            return -1

        # If command has reply additionally wait for data acknoledgement
        if (com in _command_has_reply):
            while((not(rd and 0x100)) and timeout!=0):
                rd = self.read(0x4)
                timeout -= 1
            if timeout == 0:
                return -1
            return (rd>>16)&0xffff
        else:
            return None

    def read_serial(self):
        msb = self.command("READ_SERIAL_MSB")
        lsb = self.command("READ_SERIAL_LSB")
        if (msb==-1) or (lsb==-1):
            return -1
        return (msb<<16|lsb)

    def read_channel_status(self, channel):
        if channel > 255:
            raise ValueError("Channel should be between 0 and 255")
        err = self.command("SET_CHANNEL", channel)
        if err == -1:
            return -1
        return self.command("CHANNEL_STATUS")

    def disable_channel(self, channel):
        if channel > 255:
            raise ValueError("Channel should be between 0 and 255")
        err = self.command("SET_CHANNEL", channel)
        if err == -1:
            return -1
        err = self.command("CHANNEL_CONTROL", 1)
        if err == -1:
            return -1

    def enable_channel(self, channel):
        if channel > 255:
            raise ValueError("Channel should be between 0 and 255")
        err = self.command("SET_CHANNEL", channel)
        if err == -1:
            return -1
        err = self.command("CHANNEL_CONTROL", 0)
        if err == -1:
            return -1

    def scan_all_channels(self):
        self.disabled_channel_list = []
        self.num_disabled = 0
        for i in range(256):
            self.is_channel_disabled[i] = self.read_channel_status(i)
            if(self.is_channel_disabled[i]==1):
                self.disabled_channel_list.append(i)
                self.num_disabled += 1

    def set_clock(self, clk):
        clk = int(clk/5)
        return self.command("SET_CLOCK", clk)

    def get_clock(self):
        clk = self.command("GET_CLOCK")
        if clk == -1:
            return -1
        else:
            return clk*5

    def set_threshold(self, threshold):
        threshold = int(threshold*1023.0/200.0)
        return self.command("SET_THRESHOLD", threshold)

    def get_threshold(self):
        threshold = self.command("GET_THRESHOLD")
        if threshold == -1:
            return -1
        else:
            return threshold*200.0/1023.0



# Separates data from event packets and adds to separate arrays
def parse_event_data(event_data):
    parsed_event_data = []
    for event in event_data:
        timestamp = (event & 0xffffffff00000000) >> 32
        det_id = (event & 0x00000000ff000000) >> 24
        pix_id = (event & 0x0000000000ff0000) >> 16
        energy = (event & 0x000000000000ffff) >> 0
        parsed_event_data.append((timestamp, det_id, pix_id, energy))
    return parsed_event_data
print("Functions loaded")

# Load PL overlay, access detectors via czt0 and czt1
ov = Overlay("./overlays/test_2det_commanding.bit")
print("Overlay loaded")

czt0 = ov.AXI_CZT_AXIS_0.AXI_CZT_Controller
czt1 = ov.AXI_CZT_AXIS_1.AXI_CZT_Controller
reset_pl = ov.Reset_system.reset_gpio.channel1[0].on
dma_channel = ov.DMA.axi_dma_0.recvchannel
wr_data_count = ov.AXIS_Combine.axi_gpio_0.channel1.read
rd_data_count = ov.AXIS_Combine.axi_gpio_0.channel2.read

reset_pl()
czt1.command("BREAK")
czt0.command("BREAK")

# Print detector information
reply_commands = ['READ_SERIAL_LSB',
             'READ_SERIAL_MSB',
             'READ_FIRMWARE_VERSION',
             'READ_MODULE_VERSION',
             'EEPROM_CHECKSUM',
             'GET_CLOCK',
             'GET_EMULATOR',
             'GET_GPIO',
             'GET_PEAKING_TIME',
             'GET_THRESHOLD',
             'READ_STATUS',
             'READ_TEMPERATURE']
print("Command                    CZT 0  CZT 1")
for comm in reply_commands:
    print(f"{comm:.<25}{czt0.command(comm):>7}{czt1.command(comm):>7}")

print("Reply commands done")


# Enable all pixels first
for pixel in range(0, 256):
    czt0.enable_channel(pixel)
    czt1.enable_channel(pixel)

# Disable pixels from CSV: 2 rows x 256 cols, no header
# Row 0 = det0, Row 1 = det1; 1 = disable, 0 = enable
pixel_dis_csv = dictionary.get("pixel_dis_csv", "")
if pixel_dis_csv and os.path.isfile("pixel_disable.csv"):
    pix_df = pd.read_csv("pixel_disable.csv", header=None)
    det0_dis = pix_df.iloc[0].astype(int).tolist()
    det1_dis = pix_df.iloc[1].astype(int).tolist()
    for ch in range(256):
        if det0_dis[ch] == 1:
            czt0.disable_channel(ch)
        if det1_dis[ch] == 1:
            czt1.disable_channel(ch)
    print(f"Disabled {sum(det0_dis)} pixels on det0, {sum(det1_dis)} pixels on det1")
else:
    print("No pixel_disable.csv found, all pixels enabled")

# Set clock
if dictionary["clock"] in [10, 15, 20, 25, 30]:
    czt0.set_clock(dictionary["clock"])
    czt1.set_clock(dictionary["clock"])
else:
    czt0.set_clock(10)
    czt1.set_clock(10)

# Set threshold
if dictionary["threshold"] <= 200 and dictionary["threshold"] >= 0:
    czt0.set_threshold(dictionary["threshold"])
    czt1.set_threshold(dictionary["threshold"])



event_data_buffer = allocate(shape=(128,), dtype=np.uint64)
main_buffer = []

reset_pl()
if 0 in dictionary["detector"]:
    print("0 on")
    czt0.command("EVENT_ON")

if 1 in dictionary["detector"]:
    print("1 on")
    czt1.command("EVENT_ON")
#
npackets = int(dictionary["number"]/128)

# Load events
sleep(0.05)
dma_channel.start()
dma_channel.transfer(event_data_buffer)
start_time = time.perf_counter()

if dictionary["type"] == "time":
    while (time.perf_counter() - start_time < dictionary["number"]):
        dma_channel.wait()
        main_buffer.extend(event_data_buffer.tolist())
        dma_channel.transfer(event_data_buffer)

else:
    for _ in range(npackets):
        dma_channel.wait()
        main_buffer.extend(event_data_buffer.tolist())
        dma_channel.transfer(event_data_buffer)


czt1.command("BREAK")
czt0.command("BREAK")

print("Events done")
# Check if main_buffer is empty before processing
if not main_buffer:
    print("Warning: main_buffer is empty. No data to process.")
    exit()

# Parse buffer and separate pixels, times, and energy
parse_main_buffer = parse_event_data(main_buffer)
pixels = [x[2] for x in parse_main_buffer]
det_id = [x[1] for x in parse_main_buffer]
times = [x[0] for x in parse_main_buffer]
energy = [x[3] for x in parse_main_buffer]

# Create output folder
foldername = "outputs_test/" + dictionary["output"]
filename = dictionary["output"]
os.makedirs(foldername, exist_ok=True)
print("Parsing done")

# Save CSV file
df = pd.DataFrame(parse_main_buffer, columns=["timestamp", "det_id", "pixel", "energy"])
csv_filename = os.path.join(foldername, f"{filename}_data.csv")
df.to_csv(csv_filename, index=False)

print("All files saved successfully!")
