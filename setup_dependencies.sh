#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# VL-ADK Setup Script (SAFE)
# - No destructive removals or purges
# - Avoids legacy driver installs (e.g., 530)
# - Skips distro CUDA toolkit to prevent PyTorch conflicts
# - Jetson uses system OpenCV/GStreamer; Desktop uses pip OpenCV
# - Idempotent: only installs what’s missing
# =============================================================================

echo "VL-ADK Setup Script (safe)"
echo "=========================="

# ---------- Environment detection ----------
if [ -f "/etc/nv_tegra_release" ] || grep -qi "tegra" /proc/cpuinfo 2>/dev/null; then
  ENVIRONMENT="jetson"
  echo "Detected: NVIDIA Jetson"
elif command -v system76-power >/dev/null 2>&1; then
  ENVIRONMENT="system76"
  echo "Detected: System76 Laptop (Pop!_OS)"
else
  ENVIRONMENT="desktop"
  echo "Detected: Desktop/Laptop"
fi

# Manual override
if [[ "${1:-}" == "--jetson" ]]; then
  ENVIRONMENT="jetson"; echo "Forced: Jetson mode"
elif [[ "${1:-}" == "--desktop" ]]; then
  ENVIRONMENT="desktop"; echo "Forced: Desktop mode"
elif [[ "${1:-}" == "--system76" ]]; then
  ENVIRONMENT="system76"; echo "Forced: System76 mode"
fi

echo "Environment: $ENVIRONMENT"
echo ""

# ---------- Activate venv (required) ----------
if [ -z "${VIRTUAL_ENV:-}" ]; then
  if [ -d ".venv" ]; then
    echo "Activating .venv ..."
    # shellcheck disable=SC1091
    source .venv/bin/activate
  else
    echo "ERROR: No virtualenv found at .venv/"
    echo "Create one first:  python3 -m venv .venv && source .venv/bin/activate"
    exit 1
  fi
fi

# ---------- Apt update ----------
echo "Updating package list..."
sudo apt update

# ---------- System packages (by environment) ----------
if [ "$ENVIRONMENT" = "jetson" ]; then
  echo "Installing Jetson system dependencies (OpenCV + GStreamer from system)..."
  sudo apt install -y \
    python3-gi python3-gi-cairo gir1.2-gstreamer-1.0 python3-gst-1.0 \
    libcairo2-dev libgirepository1.0-dev pkg-config libcairo-gobject2 \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    gstreamer1.0-tools \
    libopencv-dev python3-opencv \
    python3-dev build-essential

  echo "Installing TensorRT runtime headers (Jetson)..."
  sudo apt install -y \
    python3-libnvinfer python3-libnvinfer-dev \
    python3-libnvinfer-dispatch python3-libnvinfer-lean || true

elif [ "$ENVIRONMENT" = "system76" ]; then
  echo "Installing System76 desktop dependencies..."
  sudo apt install -y python3-dev build-essential libopencv-dev

  # GPU / Driver sanity (non-destructive)
  echo "Checking NVIDIA driver with nvidia-smi..."
  if nvidia-smi >/dev/null 2>&1; then
    echo "NVIDIA driver present:"
    nvidia-smi | sed -n '1,3p'
  else
    echo " NVIDIA driver not active. Installing System76 NVIDIA integration..."
    # This pulls the recommended/new driver for Pop!_OS hardware
    sudo apt install -y system76-driver-nvidia
    echo "NOTE: You may need to reboot and/or run: system76-power graphics nvidia"
  fi

  # DO NOT install distro CUDA toolkit here; PyTorch wheels include runtime.
  echo "Skipping nvidia-cuda-toolkit to avoid conflicts with PyTorch wheels."

else
  echo "Installing generic desktop dependencies..."
  sudo apt install -y python3-dev build-essential libopencv-dev

  # Optional, non-destructive driver helper:
  if lspci | grep -qi nvidia; then
    echo "NVIDIA GPU detected."
    if nvidia-smi >/dev/null 2>&1; then
      echo "NVIDIA driver present:"
      nvidia-smi | sed -n '1,3p'
    else
      echo " NVIDIA driver not active. Installing a current driver (no purge)."
      # On Ubuntu/Pop: this installs the recommended current driver
      sudo ubuntu-drivers install || true
      echo "If driver installation occurred, reboot may be required."
    fi
  fi

  echo "Skipping nvidia-cuda-toolkit to avoid PyTorch conflicts."
fi

# ---------- Python deps ----------
echo "Installing Python packages from requirements.txt (if present)..."
if [ -f "requirements.txt" ]; then
  pip install -r requirements.txt
else
  echo "(No requirements.txt found, skipping)"
fi

# ---------- PyTorch (GPU wheels; wheels include CUDA runtime) ----------
echo "Checking PyTorch installation..."
if python - <<'PY' 2>/dev/null; then
import torch, sys
print(f"Found PyTorch {torch.__version__}, CUDA available: {torch.cuda.is_available()}")
sys.exit(0)
PY
  echo "PyTorch already installed, skipping..."
else
  echo "Installing PyTorch (CUDA-enabled wheels, cu124 channel)..."
  # cu124 wheels require a reasonably new NVIDIA driver
  pip install --upgrade --no-cache-dir torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu124
fi

# ---------- Ultralytics / YOLO-E ----------
echo "Ensuring Ultralytics is installed..."
if python - <<'PY' 2>/dev/null; then
import ultralytics; print("Ultralytics present")
PY
  echo "Ultralytics already installed, skipping..."
else
  if [ "$ENVIRONMENT" = "jetson" ]; then
    echo "Installing Ultralytics (no OpenCV deps on Jetson to avoid conflicts)..."
    pip install "ultralytics>=8.0.196" --no-deps
  else
    echo "Installing Ultralytics..."
    pip install "ultralytics>=8.0.196"
  fi
fi

# ---------- Jetson-only: link system modules into venv ----------
if [ "$ENVIRONMENT" = "jetson" ]; then
  echo "Linking system Python modules into venv (Jetson)..."
  site_pkgs="$(python - <<'PY'
import sysconfig, os
print(sysconfig.get_paths()['purelib'])
PY
)"
  pushd "$site_pkgs" >/dev/null

  ln -sf /usr/lib/python3/dist-packages/gi* . || true
  ln -sf /usr/lib/python3/dist-packages/cairo* . || true
  ln -sf /usr/lib/python3/dist-packages/gobject* . || true

  if [ -d "/usr/lib/python3.10/dist-packages/tensorrt" ]; then ln -sf /usr/lib/python3.10/dist-packages/tensorrt .; fi
  if [ -d "/usr/lib/python3.10/dist-packages/tensorrt_lean" ]; then ln -sf /usr/lib/python3.10/dist-packages/tensorrt_lean .; fi
  if [ -d "/usr/lib/python3.10/dist-packages/tensorrt_dispatch" ]; then ln -sf /usr/lib/python3.10/dist-packages/tensorrt_dispatch .; fi

  # Use system OpenCV (has GStreamer) instead of pip cv2 on Jetson
  ln -sf /usr/lib/python3/dist-packages/cv2* . || true

  popd >/dev/null
fi

# ---------- System76 NVIDIA mode hint ----------
if [ "$ENVIRONMENT" = "system76" ]; then
  echo "Checking System76 graphics mode..."
  CURRENT_MODE="$(system76-power graphics 2>/dev/null || echo "unknown")"
  echo "Current graphics mode: ${CURRENT_MODE}"
  if [ "$CURRENT_MODE" != "nvidia" ]; then
    echo "TIP: To use the dGPU: sudo system76-power graphics nvidia  (then logout/login or reboot)"
  fi
fi

# ---------- Verification ----------
echo ""
echo "Verifying installations..."
echo "=========================="

python - <<'PY' || true
try:
    import torch, cv2, sys
    print("PyTorch:", torch.__version__, "| CUDA available:", torch.cuda.is_available())
    print("OpenCV:", cv2.__version__)
except Exception as e:
    print("Python verify error:", e)
PY

python - <<'PY' || true
try:
    import ultralytics
    print("Ultralytics/YOLO-E available")
except Exception as e:
    print("Ultralytics import error:", e)
PY

if [ "$ENVIRONMENT" = "jetson" ]; then
python - <<'PY' || true
try:
    import sys
    sys.path.append('jetbot-api')
    from jetbot import Camera, Robot
    print("JetBot imports successful")
except Exception as e:
    print("JetBot import error:", e)
PY
fi

echo ""
echo "Setup complete!"
if [ "$ENVIRONMENT" = "jetson" ]; then
  echo "  Run: cd jetbot-api && python3 main.py    # JetBot hardware API"
fi
echo "  Run: cd yoloe-backend && python3 main.py  # YOLO-E detection API"
echo ""
echo "Notes:"
echo " - We did NOT install distro CUDA toolkit to avoid conflicts with PyTorch wheels."
echo " - We did NOT install legacy NVIDIA drivers (e.g., 530)."
echo " - If CUDA is still not picked up in Python, verify 'nvidia-smi' works and reboot if needed."
