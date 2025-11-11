# WebSocket API Documentation

This document describes the WebSocket API for real-time telemetry and YOLO object detection.

## Connection

### Endpoint

```
ws://localhost:8001/ws/telemetry
```

### Query Parameters

-   **`client`** (optional, default: `"frontend"`): Client type identifier
    -   `"jetbot"`: JetBot client - receives JSON-only messages (no images)
    -   `"frontend"`: Frontend client - receives full telemetry with annotated images

### Connection Examples

**JetBot Client:**

```javascript
const ws = new WebSocket("ws://localhost:8001/ws/telemetry?client=jetbot");
```

**Frontend Client:**

```javascript
const ws = new WebSocket("ws://localhost:8001/ws/telemetry?client=frontend");
// or simply
const ws = new WebSocket("ws://localhost:8001/ws/telemetry");
```

### Keepalive

Send `"ping"` as a plain text message to keep the connection alive. The server will respond with `"pong"`.

```javascript
ws.send("ping");
```

---

## Client Types

### JetBot Client (`client=jetbot`)

-   **Purpose**: Low-bandwidth connection for robot control
-   **Receives**: JSON-only telemetry (no images)
-   **Sends**: Frame data for processing, label management requests
-   **Use Case**: Real-time detection results for reactive control

### Frontend Client (`client=frontend`)

-   **Purpose**: Full-featured connection for visualization
-   **Receives**: Complete telemetry with annotated images
-   **Sends**: Label management requests
-   **Use Case**: Display camera feed with bounding boxes and detections

---

## Message Types

All messages are JSON objects with a `type` field indicating the message type.

### Incoming Messages (Client → Server)

#### 1. Frame Message (JetBot only)

Send a camera frame for processing.

```json
{
    "type": "frame",
    "image": "base64_encoded_jpeg_string",
    "ultrasonic": {
        "distance_m": 0.25,
        "distance_cm": 25.0
    },
    "motors": {
        "left": 0.5,
        "right": 0.5
    }
}
```

**Fields:**

-   `type`: `"frame"` (required)
-   `image`: Base64-encoded JPEG image string (required)
-   `ultrasonic`: Object with distance readings (optional)
    -   `distance_m`: Distance in meters (float, optional)
    -   `distance_cm`: Distance in centimeters (float, optional)
-   `motors`: Object with motor values (optional)
    -   `left`: Left motor value (float, optional)
    -   `right`: Right motor value (float, optional)

**Response:** Server sends back a `detections` message (see below)

#### 2. Set Labels

Update the detection class labels.

```json
{
    "type": "set_labels",
    "labels": ["person", "bicycle", "car", "dog", "cat"]
}
```

**Fields:**

-   `type`: `"set_labels"` (required)
-   `labels`: Array of prompt strings for open-vocabulary detection (required)
    -   These are the actual classes YOLO-E will detect
    -   Can be any text descriptions (e.g., ["person", "bicycle", "red car", "dog running"])
    -   Example: `["person", "bicycle", "car"]` will detect those 3 classes
    -   The order matters - `class_id` in detections will index into this array

**Response:** Server sends back a `labels_response` message and broadcasts `labels_updated` event

**Note:** Labels are automatically included in all telemetry messages and detection responses, so there's no need for a separate `get_labels` request.

---

### Outgoing Messages (Server → Client)

#### 1. Telemetry Message (Broadcast)

Regular telemetry updates broadcast to all connected clients (~30 FPS).

**For JetBot clients:**

```json
{
  "timestamp": 1234567890.123,
  "ultrasonic": {
    "distance_m": 0.25,
    "distance_cm": 25.0
  },
  "motors": {
    "left": 0.5,
    "right": 0.5
  },
  "detections": [
    {
      "class_id": 0,
      "class_name": "person",
      "confidence": 0.95,
      "box": {
        "x1": 100.0,
        "y1": 200.0,
        "x2": 300.0,
        "y2": 400.0
      }
    }
  ],
  "num_detections": 1,
  "model": {
    "name": "yoloe-l.pt",
    "device": "cuda"
  },
  "labels": ["person", "bicycle", "car", ...]
}
```

**For Frontend clients (includes images):**

```json
{
  "timestamp": 1234567890.123,
  "ultrasonic": {
    "distance_m": 0.25,
    "distance_cm": 25.0
  },
  "motors": {
    "left": 0.5,
    "right": 0.5
  },
  "detections": [
    {
      "class_id": 0,
      "class_name": "person",
      "confidence": 0.95,
      "box": {
        "x1": 100.0,
        "y1": 200.0,
        "x2": 300.0,
        "y2": 400.0
      }
    }
  ],
  "num_detections": 1,
  "model": {
    "name": "yoloe-l.pt",
    "device": "cuda"
  },
  "labels": ["person", "bicycle", "car", ...],
  "image": "base64_encoded_jpeg_string_with_bounding_boxes",
  "raw_image": "base64_encoded_jpeg_string_original"
}
```

**Fields:**

-   `timestamp`: Unix timestamp in seconds (float)
-   `ultrasonic`: Ultrasonic sensor readings (object)
    -   `distance_m`: Distance in meters (float, nullable)
    -   `distance_cm`: Distance in centimeters (float, nullable)
-   `motors`: Motor values (object)
    -   `left`: Left motor value (float, nullable)
    -   `right`: Right motor value (float, nullable)
-   `detections`: Array of detection objects (array)
    -   `class_id`: COCO class ID (integer)
    -   `class_name`: Class name (string, uses custom labels if set)
    -   `confidence`: Detection confidence 0.0-1.0 (float)
    -   `box`: Bounding box coordinates (object)
        -   `x1`: Left coordinate (float)
        -   `y1`: Top coordinate (float)
        -   `x2`: Right coordinate (float)
        -   `y2`: Bottom coordinate (float)
-   `num_detections`: Number of detections (integer)
-   `model`: Model information (object)
    -   `name`: Model filename (string)
    -   `device`: Device used ("cuda" or "cpu")
-   `labels`: Current prompts array (array of strings)
    -   For YOLO-E, these are the current prompts being used for detection
    -   `class_id` in detections indexes into this array
-   `image`: Annotated image with bounding boxes (string, frontend only)
    -   Base64-encoded JPEG
-   `raw_image`: Original unannotated image (string, frontend only)
    -   Base64-encoded JPEG

#### 2. Detections Message (JetBot response)

Response to a `frame` message from JetBot.

```json
{
  "type": "detections",
  "detections": [
    {
      "class_id": 0,
      "class_name": "person",
      "confidence": 0.95,
      "box": {
        "x1": 100.0,
        "y1": 200.0,
        "x2": 300.0,
        "y2": 400.0
      }
    }
  ],
  "num_detections": 1,
  "model": {
    "name": "yoloe-l.pt",
    "device": "cuda"
  },
  "labels": ["person", "bicycle", "car", ...]
}
```

**Fields:**

-   `type`: `"detections"` (required)
-   `detections`: Array of detection objects (same structure as telemetry)
-   `num_detections`: Number of detections (integer)
-   `model`: Model information (object)
-   `labels`: Current prompts array (array of strings)
    -   For YOLO-E, these are the current prompts being used for detection

#### 3. Labels Response

Response to `set_labels` requests.

```json
{
  "type": "labels_response",
  "success": true,
  "labels": ["person", "bicycle", "car", ...],
  "message": "Labels updated: 5 custom labels set"
}
```

**Fields:**

-   `type`: `"labels_response"` (required)
-   `success`: Whether operation succeeded (boolean)
-   `labels`: Current prompts array (array of strings)
    -   For YOLO-E, these are the current prompts being used for detection
    -   `class_id` in detections indexes into this array
-   `message`: Status message (string, optional)

**Note:** Labels are also included in all telemetry messages and detection responses, so a separate `get_labels` request is not needed.

#### 4. Event Message

Broadcast events (e.g., label updates).

```json
{
  "type": "event",
  "event_type": "labels_updated",
  "timestamp": 1234567890.123,
  "data": {
    "labels": ["person", "bicycle", "car", ...]
  }
}
```

**Fields:**

-   `type`: `"event"` (required)
-   `event_type`: Event type identifier (string)
    -   `"labels_updated"`: Labels were changed
-   `timestamp`: Unix timestamp in seconds (float)
-   `data`: Event-specific data (object)
    -   For `labels_updated`: Contains `labels` array

---

## Event Types

### `labels_updated`

Broadcast when labels are updated via `set_labels`.

**Triggered by:** `set_labels` message from any client

**Broadcast to:** All connected clients

**Data structure:**

```json
{
  "labels": ["person", "bicycle", "car", ...]
}
```

---

## Usage Examples

### JetBot Client Example

```python
import asyncio
import websockets
import json
import base64
import cv2

async def jetbot_client():
    uri = "ws://localhost:8001/ws/telemetry?client=jetbot"

    async with websockets.connect(uri) as websocket:
        print("Connected as JetBot client")

        # Send a frame
        frame = cv2.imread("camera_frame.jpg")
        _, buffer = cv2.imencode('.jpg', frame)
        image_b64 = base64.b64encode(buffer).decode('utf-8')

        frame_message = {
            "type": "frame",
            "image": image_b64,
            "ultrasonic": {
                "distance_m": 0.25,
                "distance_cm": 25.0
            },
            "motors": {
                "left": 0.5,
                "right": 0.5
            }
        }

        await websocket.send(json.dumps(frame_message))

        # Receive detection response
        response = await websocket.recv()
        data = json.loads(response)

        if data.get("type") == "detections":
            print(f"Detected {data['num_detections']} objects")
            for det in data["detections"]:
                print(f"  - {det['class_name']}: {det['confidence']:.2f}")

asyncio.run(jetbot_client())
```

### Frontend Client Example

```javascript
const ws = new WebSocket("ws://localhost:8001/ws/telemetry?client=frontend");

ws.onopen = () => {
    console.log("Connected to telemetry stream");
    // Labels will be included in the first telemetry message
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === "event" && data.event_type === "labels_updated") {
        console.log("Labels updated:", data.data.labels);
    } else if (data.type === "labels_response") {
        console.log("Labels set:", data.labels);
    } else if (data.image) {
        // Telemetry message with image
        const img = document.createElement("img");
        img.src = `data:image/jpeg;base64,${data.image}`;
        document.body.appendChild(img);

        console.log(`Detections: ${data.num_detections}`);
        data.detections.forEach((det) => {
            console.log(`  - ${det.class_name}: ${det.confidence.toFixed(2)}`);
        });
    }
};

// Update labels
function setLabels(labels) {
    ws.send(
        JSON.stringify({
            type: "set_labels",
            labels: labels,
        })
    );
}
```

### Label Management Example

```javascript
// Set custom labels
ws.send(
    JSON.stringify({
        type: "set_labels",
        labels: ["person", "bicycle", "car", "motorcycle", "airplane"],
    })
);

// Labels are automatically included in:
// - All telemetry messages (data.labels)
// - All detection responses (data.labels)
// - labels_updated events (data.data.labels)
// No need to request them separately!
```

---

## Error Handling

### Connection Errors

-   Connection failures will result in WebSocket disconnection
-   Clients should implement reconnection logic with exponential backoff

### Message Errors

-   Invalid JSON will be logged but connection remains open
-   Missing required fields may result in no response
-   Invalid message types are ignored

### Processing Errors

-   Frame processing errors are logged server-side
-   Detection failures don't disconnect the client
-   Label update failures return `success: false` in response

---

## Performance Notes

-   **Frame Rate**: Telemetry broadcasts at ~30 FPS (33ms interval)
-   **Image Quality**: JPEG encoded at 85% quality
-   **Bandwidth**:
    -   JetBot clients: ~1-5 KB per message (JSON only)
    -   Frontend clients: ~50-200 KB per message (with images)
-   **Latency**:
    -   Frame processing: ~50-200ms (depends on GPU/CPU)
    -   WebSocket overhead: <10ms

---

## Notes

-   **Label Mapping**: YOLO-E uses open-vocabulary prompts. Labels define what the model detects, not just display names.
-   **Class IDs**: Detection `class_id` indexes into the current prompts array (0 to len(prompts)-1)
-   **Bounding Boxes**: Coordinates are in pixel space (x1, y1 = top-left, x2, y2 = bottom-right)
-   **Confidence**: Values range from 0.0 to 1.0
-   **Image Format**: All images are JPEG encoded as base64 strings
