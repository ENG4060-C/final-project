# ADK Backend - Multi-Agent Robot Control

Multi-agent system for controlling the JetBot using Google ADK.

## Architecture

-   **Director**: Receives goals, decides if simple (execute directly) or complex (initialize mission)
-   **Observer**: Vision specialist, finds and tracks objects
-   **Pilot**: Movement specialist, navigates based on Observer's findings

## Running the System

### Option 1: ADK API Server + Frontend (Recommended)

**Terminal 1 - ADK API:**

```bash
cd adk-backend
./run_api.sh
```

This starts the ADK API server on port 8003.

**Terminal 2 - Frontend:**

```bash
cd frontend
npm run dev
```

Then open `http://localhost:3000` and use the Agent Chat panel on the right.

### Option 2: Using ADK Web UI

```bash
cd adk-backend
adk web app:root_agent --port 8003
```

This opens the ADK web interface at `http://localhost:8003`.

### Option 3: Using Custom CLI with Auto-Telemetry

```bash
cd adk-backend
python main.py
```

This runs a custom CLI that automatically injects telemetry into agent context every turn.

## Prerequisites

Make sure these services are running:

1. **JetBot API** (port 8000):

    ```bash
    cd jetbot-backend
    python main.py
    ```

2. **YOLO-E Vision Backend** (port 8002):

    ```bash
    cd yoloe-backend
    python main.py
    ```

3. **Environment**:
    - Create `.env` file with `GOOGLE_API_KEY=your_key_here`

## Tools Available

### Movement

-   `move_distance(distance_m, speed)` - Move forward (+) or backward (-)
-   `rotate_robot(angle_degrees, speed)` - Rotate counter-clockwise (+) or clockwise (-)
-   `move_arc(radius_m, angle_degrees, speed)` - Move in curved path
-   `stop_robot()` - Emergency stop

### Vision

-   `get_telemetry()` - Get real-time ultrasonic + detection data
-   `view_query(query, orientation)` - See current camera view
-   `set_vision_labels(labels)` - Configure what objects to detect
-   `scan_surroundings(labels)` - 360° scan
-   `rotate_until_centered(target_object)` - Center on object

### Mission Control

-   `initialize_mission(goal, plan)` - Set up complex missions (Director only)
-   `mission_complete(reason)` - Signal mission done

## Telemetry

Real-time sensor data available to all agents:

-   **Ultrasonic distance**: 0.02m to 4.0m range (avoid obstacles <0.3m)
-   **Vision detections**: Objects with bounding boxes, orientation, rotation degree
-   **Active labels**: What the vision system is currently detecting

## Example Usage

### Simple Command

```
User: "Move forward 1 meter"
Director: [Executes move_distance(1.0), calls mission_complete]
```

### Complex Mission

```
User: "Find a bottle and center on it"
Director: [Calls initialize_mission with plan]
Observer: [Uses view_query to find bottle]
Pilot: [Uses rotate_robot based on Observer's rotation_degree]
Observer: [Calls rotate_until_centered, then mission_complete]
```
