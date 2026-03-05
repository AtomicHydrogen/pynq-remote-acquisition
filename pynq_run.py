"""
PYNQ CZT Runner - No GUI, single sequential script.
Usage: python pynq_run.py [path_to_yaml] [local_output_dir]
Dependencies: pip install paramiko pyyaml numpy pandas matplotlib seaborn
"""

import paramiko
import os
import sys
import argparse
import getpass
import yaml
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime


def connect(ip, user, password):
    print(f"Connecting to {user}@{ip}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username=user, password=password, timeout=10)
    print("Connected.")
    return client


def sudo_exec(client, cmd, password, timeout=300):
    full_cmd = "echo '" + password + "' | sudo -S " + cmd
    stdin, stdout, stderr = client.exec_command(full_cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    code = stdout.channel.recv_exit_status()
    return out, err, code


def send_file(client, local_path, remote_name, password, pynq_path):
    """SFTP to /tmp then sudo mv to target dir."""
    print(f"Uploading {os.path.basename(local_path)} -> {remote_name}...")
    sftp = client.open_sftp()
    sftp.put(local_path, f"/tmp/{remote_name}")
    sftp.close()
    out, err, code = sudo_exec(client, f"mv /tmp/{remote_name} {pynq_path}/{remote_name}", password)
    if code != 0:
        print(f"ERROR moving {remote_name}: {err}")
        return False
    print(f"  Uploaded to {pynq_path}/{remote_name}")
    return True


def run_test(client, password, pynq_path):
    """Run test.py, return (success, stdout_text)."""
    print("Running test.py on PYNQ...")
    cmd = "-E bash -lc 'cd " + pynq_path + " && /usr/local/share/pynq-venv/bin/python3 " + pynq_path + "/test.py'"
    out, err, code = sudo_exec(client, cmd, password, timeout=300)
    if out:
        print(out)
    if err:
        err_lines = [l for l in err.split("\n") if "password" not in l.lower()]
        err_clean = "\n".join(err_lines).strip()
        if err_clean:
            print(f"[stderr]: {err_clean}")
    if code != 0:
        print(f"Script failed with exit code {code}")
        return False, out
    print("test.py finished.")
    return True, out


def get_csv(client, output_name, local_dest, password, pynq_path):
    remote_folder = f"{pynq_path}/outputs_test/{output_name}"
    print(f"Fetching CSV from {remote_folder}...")

    out, err, code = sudo_exec(client, f"ls {remote_folder}/*.csv", password)
    if code != 0:
        print(f"No CSV found: {err.strip()}")
        return None

    csv_files = [os.path.basename(f.strip()) for f in out.strip().split("\n") if f.strip()]
    if not csv_files:
        print("No CSV files found.")
        return None

    os.makedirs(local_dest, exist_ok=True)

    downloaded = []
    for cf in csv_files:
        remote_file = f"{remote_folder}/{cf}"
        tmp_file = f"/tmp/{cf}"
        sudo_exec(client, f"cp {remote_file} {tmp_file} && chmod 644 {tmp_file}", password)
        sftp = client.open_sftp()
        local_file = os.path.join(local_dest, cf)
        sftp.get(tmp_file, local_file)
        sftp.close()
        sudo_exec(client, f"rm {tmp_file}", password)
        print(f"  Downloaded: {cf}")
        downloaded.append(local_file)

    print("CSV transfer complete.")
    return downloaded


def load_pixel_disable(pixel_dis_csv):
    """Load 2-row x 256-col pixel disable CSV.
    Returns two lists of 256 ints (det0, det1)."""
    df = pd.read_csv(pixel_dis_csv, header=None)
    det0 = df.iloc[0].astype(int).tolist()
    det1 = df.iloc[1].astype(int).tolist()
    assert len(det0) == 256 and len(det1) == 256, "pixel_disable.csv must be 2 rows x 256 cols"
    return det0, det1


def write_output_txt(filepath, cfg, prefix, test_stdout, det0_dis, det1_dis):
    """Write output.txt with reproducible YAML header + metadata + pixel disable."""
    with open(filepath, "w") as f:
        # --- Reproducible YAML (first K lines) ---
        f.write("---\n")
        # Connection
        f.write(f'pynq_ip: "{cfg["pynq_ip"]}"\n')
        f.write(f'pynq_user: "{cfg["pynq_user"]}"\n')
        f.write(f'pynq_path: "{cfg["pynq_path"]}"\n')
        # Science params
        f.write(f'detector: {cfg["detector"]}\n')
        f.write(f'type: "{cfg["type"]}"\n')
        if cfg["type"] == "time":
            f.write(f'time_s: {cfg["time_s"]}\n')
        else:
            f.write(f'n_events: {cfg["n_events"]}\n')
        f.write(f'pixel_dis_csv: "{cfg.get("pixel_dis_csv", "pixel_disable.csv")}"\n')
        f.write(f'clock: {cfg["clock"]}\n')
        f.write(f'threshold_keV: {cfg["threshold_keV"]}\n')
        f.write("\n")

        # --- Metadata: reply commands from test.py stdout ---
        f.write("# --- Reply Commands (from test.py) ---\n")
        # Try to extract the reply commands table from stdout
        in_table = False
        for line in test_stdout.split("\n"):
            line_s = line.strip()
            if line_s.startswith("Command") and "CZT" in line_s:
                in_table = True
                f.write(f"# {line_s}\n")
                continue
            if in_table:
                if line_s == "" or line_s.startswith("Reply commands done"):
                    break
                f.write(f"# {line_s}\n")
        f.write("\n")

        # --- Run info ---
        f.write(f"# Run prefix: {prefix}\n")
        f.write(f"# Timestamp: {datetime.now().isoformat()}\n")
        f.write("\n")

        # --- Pixel disable (last 2 lines, copy-pastable into CSV) ---
        f.write("# --- Pixel Disable (last 2 lines = det0, det1; copy into CSV) ---\n")
        f.write(",".join(str(v) for v in det0_dis) + "\n")
        f.write(",".join(str(v) for v in det1_dis) + "\n")


def plot_results(csv_path, prefix):
    save_dir = os.path.dirname(csv_path)
    print(f"Plotting from {os.path.basename(csv_path)}...")

    df = pd.read_csv(csv_path)
    pixels = df["pixel"].values
    det_ids = df["det_id"].values
    energy = df["energy"].values
    times = df["timestamp"].values

    unique_dets = sorted(df["det_id"].unique())

    # DPH per detector
    for det in unique_dets:
        mask = det_ids == det
        det_pixels = pixels[mask]
        if len(det_pixels) == 0:
            continue
        pixhist = np.bincount(det_pixels, minlength=256)[:256]
        fig, ax = plt.subplots(figsize=(12, 10))
        sns.heatmap(pixhist.reshape((16, 16)), cmap="icefire",
                    linewidths=1, annot=True, fmt=".0f", ax=ax)
        ax.set_title(f"Detector Plane Histogram - Det {det}")
        path = os.path.join(save_dir, f"{prefix}_dph_det{det}.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        print(f"  Saved {os.path.basename(path)}")

    # Combined DPH if both detectors present
    if len(unique_dets) > 1:
        pixhist_all = np.bincount(pixels, minlength=256)[:256]
        fig, ax = plt.subplots(figsize=(12, 10))
        sns.heatmap(pixhist_all.reshape((16, 16)), cmap="icefire",
                    linewidths=1, annot=True, fmt=".0f", ax=ax)
        ax.set_title("Detector Plane Histogram - Combined")
        path = os.path.join(save_dir, f"{prefix}_dph_combined.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        print(f"  Saved {os.path.basename(path)}")

    # Energy Spectrum overlaid per detector
    fig, ax = plt.subplots(figsize=(14, 7))
    for det in unique_dets:
        mask = det_ids == det
        ax.hist(energy[mask], bins=range(0, 4096, 10), histtype="step", label=f"Det {det}")
    if len(unique_dets) > 1:
        ax.legend()
    ax.set_xlabel("Energy (raw)")
    ax.set_ylabel("Counts")
    ax.set_title("Energy Spectrum")
    ax.grid(True)
    path = os.path.join(save_dir, f"{prefix}_spectrum.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"  Saved {os.path.basename(path)}")

    # Light Curve per detector (counts per bin)
    # Timestamps are in 100ns ticks (10MHz clock), convert to ms
    times_ms = times * 100e-9 * 1e3
    if len(times_ms) > 0 and np.max(times_ms) > 0:
        bin_width = 10  # ms
        bin_edges = np.arange(0, np.max(times_ms) + bin_width, bin_width)
        fig, ax = plt.subplots(figsize=(10, 5))
        for det in unique_dets:
            mask = det_ids == det
            counts, _ = np.histogram(times_ms[mask], bins=bin_edges)
            bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
            ax.plot(bin_centers, counts, marker=".", linestyle="-", label=f"Det {det}", markersize=3)
        if len(unique_dets) > 1:
            ax.legend()
        ax.set_xlabel("Time (ms)")
        ax.set_ylabel("Counts")
        ax.set_title(f"Light Curve ({bin_width}ms bins)")
        ax.grid(True)
        path = os.path.join(save_dir, f"{prefix}_lightcurve.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        print(f"  Saved {os.path.basename(path)}")

    print("\nAll plots saved. Showing windows... (close to exit)")
    plt.show()


def main():
    parser = argparse.ArgumentParser(description="PYNQ CZT Runner")
    parser.add_argument("--input", required=True, help="Path to YAML config file")
    parser.add_argument("--output_dir", default=".", help="Local output directory (default: ./)")
    args = parser.parse_args()

    local_yaml = args.input
    local_output_dir = args.output_dir

    if not os.path.isfile(local_yaml):
        print(f"YAML not found: {local_yaml}")
        sys.exit(1)
    os.makedirs(local_output_dir, exist_ok=True)

    with open(local_yaml, "r") as f:
        cfg = yaml.safe_load(f)

    # Connection params from YAML
    pynq_ip = cfg["pynq_ip"]
    pynq_user = cfg["pynq_user"]
    pynq_path = cfg["pynq_path"]

    run_type = cfg.get("type", "time")
    threshold = cfg.get("threshold_keV", 0)
    pixel_dis_csv = cfg.get("pixel_dis_csv", "")

    # Get the run parameter based on type
    if run_type == "time":
        run_param = cfg["time_s"]
        type_short = "t"
    else:
        run_param = cfg["n_events"]
        type_short = "e"

    # Resolve pixel_dis_csv relative to YAML location
    if pixel_dis_csv and not os.path.isabs(pixel_dis_csv):
        pixel_dis_csv = os.path.join(os.path.dirname(os.path.abspath(local_yaml)), pixel_dis_csv)

    # Load pixel disable data
    if pixel_dis_csv and os.path.isfile(pixel_dis_csv):
        det0_dis, det1_dis = load_pixel_disable(pixel_dis_csv)
    else:
        det0_dis = [0] * 256
        det1_dis = [0] * 256
        if pixel_dis_csv:
            print(f"WARNING: pixel_dis_csv '{pixel_dis_csv}' not found, all pixels enabled")

    # Build prefix: timestamp_t/e_params_thresholdkeV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if run_type == "time":
        prefix = f"{timestamp}_{type_short}_{run_param}s_{threshold}keV"
    else:
        prefix = f"{timestamp}_{type_short}_{run_param}_{threshold}keV"

    # Output folder is the prefix
    local_dest = os.path.join(local_output_dir, prefix)

    # Build the YAML that test.py will see (uses "number" internally)
    pynq_cfg = {
        "detector": cfg["detector"],
        "type": run_type,
        "number": run_param,
        "pixel_dis_csv": "pixel_disable.csv" if pixel_dis_csv else "",
        "clock": cfg["clock"],
        "threshold": threshold,
        "output": prefix,
    }

    # Write temp YAML for upload
    yaml_dir = os.path.dirname(os.path.abspath(local_yaml))
    tmp_yaml = os.path.join(yaml_dir, ".test_upload.yaml")
    with open(tmp_yaml, "w") as f:
        yaml.safe_dump(pynq_cfg, f, default_flow_style=False)

    # Write temp pixel disable CSV in 2-row format for upload
    tmp_pix_csv = os.path.join(yaml_dir, ".pixel_disable_upload.csv")
    with open(tmp_pix_csv, "w") as f:
        f.write(",".join(str(v) for v in det0_dis) + "\n")
        f.write(",".join(str(v) for v in det1_dis) + "\n")

    password = getpass.getpass(f"Password for {pynq_user}@{pynq_ip}: ")

    client = connect(pynq_ip, pynq_user, password)
    test_stdout = ""
    try:
        # Upload YAML
        if not send_file(client, tmp_yaml, "test.yaml", password, pynq_path):
            sys.exit(1)

        # Upload pixel disable CSV
        if pixel_dis_csv and os.path.isfile(pixel_dis_csv):
            if not send_file(client, tmp_pix_csv, "pixel_disable.csv", password, pynq_path):
                sys.exit(1)

        # Run
        success, test_stdout = run_test(client, password, pynq_path)
        if not success:
            sys.exit(1)

        # Get CSV
        csv_files = get_csv(client, prefix, local_dest, password, pynq_path)
    finally:
        client.close()
        for tmp in [tmp_yaml, tmp_pix_csv]:
            if os.path.exists(tmp):
                os.remove(tmp)
        print("SSH disconnected.")

    # Write output.txt
    os.makedirs(local_dest, exist_ok=True)
    output_txt = os.path.join(local_dest, f"{prefix}_output.txt")
    write_output_txt(output_txt, cfg, prefix, test_stdout, det0_dis, det1_dis)
    print(f"Saved {os.path.basename(output_txt)}")

    if csv_files:
        for csv_path in csv_files:
            plot_results(csv_path, prefix)
    else:
        print("No CSV to plot.")


if __name__ == "__main__":
    main()
