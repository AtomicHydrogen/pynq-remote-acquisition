## PYNQ Remote Acquisition Usage Guide

### Setup

#### Please go through setup.pdf before performing the steps in this document.

### On the PC

In whichever working folder you use, ensure the venv is installed as mentioned in the installation guide.

### On the PYNQ

```
/home/xilinx/jupyter_notebooks/path_to_your_folder
```

For example, on our setup we have:

```
/home/xilinx/jupyter_notebooks/cubesat
```

This must be set in double quotes as the path in `test.yaml` (config file).

E.g.: `pynq_path: "/home/xilinx/jupyter_notebooks/cubesat"`

This path must necessarily contain the following files:

1. `overlays/test_2det_commanding.bit` (`overlays` is a directory containing the bitstream)
2. `test.py`

### Running the Script

Once this is configured, the script can be run as follows (bash):

```bash
source ./your_venv_name/bin/activate
python pynq_run.py --input your_config_file --output_dir your_output_dir
```

E.g.: to produce the output in the same folder (`./`) with config file `test.yaml` also located in the same folder:

```bash
python pynq_run.py --input test.yaml --output_dir ./
```

The second argument (`--output_dir`) can be omitted and the script will create the result directory in the current working directory, i.e.:

```bash
python pynq_run.py --input test.yaml
```

Please note that both of these files (input and output_dir) can have any arbitrary path. We use the same folder in the demo only for convenience.

### `.yaml` Configuration Parameters

Note that the `.yaml` file is a plaintext file that can be created and edited in any editor.

- **`pynq_ip`**: This is usually configured as `192.168.2.99` (same as the Jupyter Notebook IP address).
- **`pynq_user`**: This is the user to SSH into. By default, this is `xilinx`.
- **`pynq_path`**: As mentioned above, this is the path to the directory containing `test.py` and the overlay bitstream file.
- **`detector`**: Indicates which detectors to use. `[0, 1]` → use both 0 and 1, `[0]` → only 0, `[1]` → only 1.
- **`type`**: Indicates the type of acquisition. `"time"` for time-based acquisition and `"event"` for event-based acquisition.
- **`time_s`**: The time in seconds for time-based acquisition. This is ignored for event-based acquisition.
- **`n_events`**: The target number of events to log for event-based acquisition. This is ignored for time-based acquisition. Note that the number of events will be rounded down to the nearest multiple of 128, i.e. `floor(n_events / 128) * 128`.
- **`pixel_dis_csv`**: The path pointing to the CSV containing the list of pixels to disable for detectors 0 and 1. There are two rows corresponding to each detector, with the 1st row for detector 0 and the 2nd for detector 1. Starting from the leftmost element, each element in the row is indexed 0–255, which corresponds to the pixel ID. Setting a `1` in any of these will disable the corresponding pixel.
- **`clock`**: SCLK frequency in MHz — this is always 10 for now.
- **`threshold_keV`**: The desired detection threshold in keV.

An example of a valid `.yaml` file is appended with the files.

```yaml
---
pynq_ip: "192.168.2.99"
pynq_user: "xilinx"
pynq_path: "/home/xilinx/jupyter_notebooks/cubesat"
detector: [0, 1]
type: "time"
time_s: 0.1
n_events: 1024
pixel_dis_csv: "pixel_disable.csv"
clock: 10
threshold_keV: 30
```

This implies the following:

PYNQ IP is configured as `192.168.2.99`, PYNQ user is `xilinx`, with `test.py` and the `overlays` directory stored within the `cubesat` directory. In this setup, both detectors 0 and 1 are used in time-based acquisition for 0.1 s, with a threshold of 30 keV. The path of the CSV implies that `pixel_disable.csv` is contained in the same working folder as `pynq_run.py`.

### Output

All data products will be generated in your selected output directory. They will be contained inside a folder labelled as `{timestamp}_{type}_{number}_{threshold}keV`. This folder will contain:

- **DPH** — Up to 2 Detector Plane Histograms, labelled with detector ID, if both detectors produced events or were used.
- **Light curve** — Event counts binned over time, 10ms time bins are used.
- **Spectrum** — Energy spectrum histogram.
- **`output.txt`** — Input parameters, runtime data, and disabled pixels.