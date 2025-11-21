# JetBot Autonomous Robot System

Multi-agent AI system for controlling a NVIDIA JetBot with vision-based navigation.

## Architecture

```
Frontend (Next.js)  →  ADK API (port 8003)  →  Director/Observer/Pilot Agents
                                                      ↓
                    →  JetBot API (port 8000)  ←  Movement Commands
                                                      ↓
                    →  YOLO-E Vision (port 8002) ← Detection/Telemetry
                                                      ↓
                                            JetBot Hardware
```

## Quick Start

### 1. Setup Dependencies

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Run setup script
./setup_dependencies.sh --system76  # or --desktop or --jetson
```

### 2. Configure Environment

Create `.env` file in `adk-backend/`:
```bash
OPENROUTER_API_KEY=your_openrouter_key_here
GOOGLE_API_KEY=your_google_key_here
```

### 3. Start Services (4 terminals)

**Terminal 1 - JetBot Backend (Hardware Control):**
```bash
cd jetbot-backend
source ../.venv/bin/activate
python main.py
# Runs on port 8000
```

**Terminal 2 - YOLO-E Backend (Vision):**
```bash
cd yoloe-backend
source ../.venv/bin/activate
python main.py
# Runs on port 8002 (CUDA accelerated on RTX 5080+)
```

**Terminal 3 - ADK Agent API:**
```bash
cd adk-backend
source ../.venv/bin/activate
./run_api.sh
# Runs on port 8003
```

**Terminal 4 - Frontend:**
```bash
cd frontend
npm install  # First time only
npm run dev
# Runs on port 3000
```

### 4. Use the System

Open `http://localhost:3000` and use the **Agent Chat** panel:
- Type commands like: "find a bottle", "scan the room", "move forward 1 meter"
- Watch the camera feed and telemetry
- See the agent reasoning and tool calls in the chat

## Components

### Backend Services

- **`jetbot-backend/`**: Hardware control API (motors, ultrasonic sensor)
- **`yoloe-backend/`**: YOLO-E vision system with WebSocket telemetry
- **`adk-backend/`**: Multi-agent AI system using Google ADK + OpenRouter

### Frontend

- **`frontend/`**: Next.js web UI with:
  - Live camera feed from JetBot
  - Agent chat interface
  - YOLO prompts configuration
  - Keyboard controls

### Agent Architecture

- **Director** (Nvidia Nemotron): Receives goals, decides simple vs complex
- **Observer** (Qwen 2.5): Vision specialist, finds objects
- **Pilot** (Qwen 2.5): Movement specialist, executes navigation

## Features

- ✅ Real-time camera feed with YOLO-E object detection
- ✅ Multi-agent reasoning system (Director/Observer/Pilot)
- ✅ Ultrasonic distance sensing for collision avoidance
- ✅ GPU-accelerated vision (RTX 5080 with PyTorch nightly)
- ✅ Open-vocabulary detection (detect any object by text prompt)
- ✅ WebSocket telemetry streaming
- ✅ Modern React UI with live updates

## Models Used

- **Director**: `openrouter/nvidia/llama-3.1-nemotron-70b-instruct`
- **Observer**: `openrouter/qwen/qwen-2.5-72b-instruct`
- **Pilot**: `openrouter/qwen/qwen-2.5-72b-instruct`

## Ports

- `8000`: JetBot hardware control API
- `8002`: YOLO-E vision backend (HTTP + WebSocket)
- `8003`: ADK agent API
- `3000`: Frontend web UI

## Testing

Test WebSocket telemetry:
```bash
cd yoloe-backend
python test_websocket.py
```

## Troubleshooting

**CUDA not working:**
- Make sure graphics mode is set to NVIDIA: `sudo system76-power graphics nvidia`
- Reboot after changing graphics mode
- Verify with: `nvidia-smi`

**Agents not triggering:**
- Ensure OPENROUTER_API_KEY is in `.env`
- Check logs for model errors
- Verify backends are running (ports 8000, 8002)

**WebSocket not connecting:**
- Make sure yoloe-backend is running
- Check if JetBot is sending frames
- Test with `curl http://localhost:8002/current-detections`

