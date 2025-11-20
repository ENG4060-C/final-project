"use client";

export function connectJetBot(onMessage: (data: any) => void) {
  const ws = new WebSocket("ws://localhost:8002/ws/telemetry");

  ws.onopen = () => {
    console.log("Connected to JetBot backend");
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch (_) {
      console.warn("Non-JSON message:", event.data);
    }
  };

  ws.onerror = (err) => console.error("WS error:", err);
  ws.onclose = () => console.log("WS closed");

  return ws;
}