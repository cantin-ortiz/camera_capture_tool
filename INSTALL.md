# Installation Guide

This guide covers setting up the Camera Capture Tool using a Python virtual environment.

## Table of Contents

1. [**Install Python 3.10.11**](#step-1-install-python-31011) - Set up Python on your computer (~10 minutes)
2. [**Install FLIR Spinnaker SDK**](#step-2-install-flir-spinnaker-sdk) - Camera control software (~15 minutes)
3. [**Download the Camera Capture Tool**](#step-3-download-the-camera-capture-tool) - Get the code from GitHub (~5 minutes)
4. [**Create Virtual Environment**](#step-4-create-virtual-environment) - Isolated Python environment (~5 minutes)
5. [**Install Python Dependencies**](#step-5-install-python-dependencies) - Required packages (~10 minutes)
6. [**Configure the Tool**](#step-6-configure-the-tool) - Adjust settings (~5 minutes)
7. [**Verify Installation**](#step-7-verify-installation) - Test everything works (~2 minutes)
8. [**Troubleshooting**](#troubleshooting) - Common issues and solutions

**Total estimated time:** ~50 minutes

## Step 1: Install Python 3.10.11

### Check if Python is already installed

Before installing Python, check if you already have it on your computer:

1. Open **PowerShell** or **Command Prompt**:
   - For instance, press `Windows Key + R`
   - Then Type `powershell` and press Enter

2. Type the following command and press Enter:
   ```powershell
   python --version
   ```

3. Look at the response:
   - **If you see something like "Python 3.x.x"**: Python is already installed! Note the version number.
   - **If you see an error or "command not found"**: Python is not installed (or not in PATH).

4. If Python is installed, also check for the Python launcher:
   ```powershell
   py --list
   ```
   - This shows all installed Python versions
   - If you see version 3.10.11 listed, you can skip to Step 2

### If you don't have Python installed:

1. Download Python 3.10.11 from [python.org](https://www.python.org/downloads/release/python-31011/)
   - Click "Windows installer (64-bit)" under "Files" at the bottom of the page
2. Run the downloaded installer
3. **Important**: During installation:
   - ✓ Check "Add Python to PATH"
   - ✓ Check "Install launcher for all users (recommended)"
4. Click "Install Now"
5. Verify installation by opening a **new** PowerShell window and typing:
   ```powershell
   python --version
   # Should output: Python 3.10.11
   ```

### If you already have a different Python version installed:

Don't worry! Python 3.10.11 can be installed alongside your existing version without breaking anything.

1. Download Python 3.10.11 from [python.org](https://www.python.org/downloads/release/python-31011/)
   - Click "Windows installer (64-bit)" under "Files"
2. Run the installer
3. During installation:
   - **Uncheck** "Add Python to PATH" (to avoid conflicts with your existing version)
   - ✓ Check "Install launcher for all users (recommended)"
   - Click "Customize installation" → "Next" → Note the installation path (typically: `C:\Users\YourUsername\AppData\Local\Programs\Python\Python310\`)
4. After installation, open a **new** PowerShell window and verify:
   ```powershell
   py -3.10 --version
   # Should output: Python 3.10.11
   ```

**Note:** The `py` launcher allows you to select which Python version to use. You'll use `py -3.10` instead of `python` when creating the virtual environment.

## Step 2: Install FLIR Spinnaker SDK

You need to install two separate components from FLIR: the Spinnaker SDK and the PySpin Python wrapper.

**Note:** Downloading from FLIR requires creating a free account. Alternatively, these installers are available on the lab server (`biotin4.hpc.uio.no\Analyses\scripts\camera_synchronisation\installers`).

### Part 1: Install Spinnaker SDK Full

1. Go to [FLIR's Spinnaker SDK download page](https://www.flir.com/products/spinnaker-sdk/)
   - Click "Download" or "Latest Spinnaker Downloads"
   - You may need to create a free FLIR account and log in

2. Download **"Spinnaker SDK Full - Windows"**
   - Choose the 64-bit version
   - Version 3.x or later (e.g., Spinnaker 3.2.0.62)
   - File size is typically ~250 MB

3. Run the downloaded installer (e.g., `SpinnakerSDK_FULL_3.2.0.62_x64.exe`)
   - Click "Next" through the setup wizard
   - Accept the license agreement
   - Use default installation path: `C:\Program Files\FLIR Systems\Spinnaker\`
   - **Important:** Make sure "Install drivers" is checked
   - Complete the installation

### Part 2: Download PySpin for Python 3.10

1. On the same FLIR download page, find **"Latest Python Spinnaker Downloads"**

2. Download **"Spinnaker Python - Windows"** for **Python 3.10**
   - Look for a file like: `spinnaker_python-4.3.0.189-cp310-cp310-win_amd64.zip`
   - The `cp310` indicates Python 3.10 compatibility
   - File size is typically ~20 MB

3. Extract the downloaded ZIP file to a temporary location (e.g., your `Downloads` folder)

4. Inside the extracted folder, locate the `.whl` file:
   ```
   spinnaker_python-4.3.0.189-cp310-cp310-win_amd64.whl
   ```
   Keep note of this file's location - you'll need it in Step 5.


## Step 3: Download the Camera Capture Tool

### Option A: Download as ZIP (recommended for most users)

1. Go to the GitHub repository: https://github.com/cantin-ortiz/camera_capture_tool

2. Click the green **"Code"** button (top right of the file list)

3. Click **"Download ZIP"**

4. Once downloaded, locate the ZIP file (usually in your `Downloads` folder)

5. **Extract the ZIP file**:
   - Right-click on `camera_capture_tool-main.zip`
   - Select "Extract All..."
   - Choose a location like `C:\Users\YourUsername\Documents\`
   - Click "Extract"

6. **Rename the folder** (optional but recommended):
   - The extracted folder will be named `camera_capture_tool-main`
   - Rename it to just `camera_capture_tool` (remove the `-main` suffix)

7. Open PowerShell and navigate to the folder:
   ```powershell
   cd C:\Users\YourUsername\Documents\camera_capture_tool
   ```

### Option B: Clone with Git (if you have Git installed)

```powershell
cd C:\Users\YourUsername\Documents
git clone https://github.com/cantin-ortiz/camera_capture_tool.git
cd camera_capture_tool
```

## Step 4: Create Virtual Environment

### If Python 3.10.11 is your only/default Python:

```powershell
# Create virtual environment in parent directory
cd ..
python -m venv env_camera
```

### If you have multiple Python versions installed:

```powershell
# Create virtual environment using Python 3.10.11 specifically
cd ..
py -3.10 -m venv env_camera
```

### Activate the virtual environment:

```powershell
# Activate the virtual environment
.\env_camera\Scripts\Activate.ps1

# If you get an execution policy error, run:
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

You should see `(env_camera)` at the beginning of your command prompt, indicating the virtual environment is active.

## Step 5: Install Python Dependencies

```powershell
cd camera_capture_tool

# Install standard packages
pip install -r requirements.txt

# Install PySpin (adjust path to match your Spinnaker version)
pip install "C:\Program Files\FLIR Systems\Spinnaker\bin64\vs2015\SpinnakerPython_C-3.2.0.62-cp310-cp310-win_amd64.whl"
```

**Note:** The wheel filename will vary based on your Spinnaker version. Use the actual filename from your installation.

## Step 6: Configure the Tool

1. Open `config.py` in a text editor (Notepad, VS Code, or any text editor)

2. Verify `VENV_PATH` points to your virtual environment:
   ```python
   VENV_PATH = "../env_camera"
   ```
   **Note:** The `..` means "one folder up" from the current folder. Since your virtual environment is in the parent directory of `camera_capture_tool`, this path is correct.

3. Adjust other settings as needed:
   - `DEFAULT_FRAMERATE`: Camera recording speed (default: 50 Hz)
   - `DEFAULT_LINE`: GPIO output line for synchronization (default: 2)
   - `DEFAULT_SAVE_PATH`: Where recordings will be saved (default: `~/Documents/flea3_recordings`)

4. Save the file and close the editor

## Step 7: Verify Installation

```powershell
# Make sure virtual environment is activated
.\start_recording.bat
```

The program should start without errors. Press `q` to quit.