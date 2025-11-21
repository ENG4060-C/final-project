"use client";

import { useEffect, useRef, useState } from "react";
import AgentChat from "../app/agent-chat";
import { useWASDControls } from './keyControls';

const JETBOT_API_BASE = 'http://localhost:8000';

export default function Home() {
    const [prompts, setPrompts] = useState<string[]>([]);
    const [inputValue, setInputValue] = useState("");
    const wsRef = useRef<WebSocket | null>(null);

    // speed sliders
    const [linearSpeed, setLinearSpeed] = useState(0.7);
    const [angularSpeed, setAngularSpeed] = useState(0.5);

    useEffect(() => {
        console.log("Connecting to JetBot WebSocket…");

        const ws = new WebSocket('ws://localhost:8002/ws/telemetry');
        wsRef.current = ws;

        ws.addEventListener("open", () => {
            console.log("JetBot WS CONNECTED");
        });

        ws.addEventListener("message", (event) => {
            try {
                const msg = JSON.parse(event.data);

                // Handle label events
                if (msg.type === "event" && msg.event_type === "labels_updated") {
                    const labels = msg.data?.labels;
                    if (Array.isArray(labels)) {
                        console.log("Labels updated from backend:", labels);
                        setPrompts(labels);
                    }
                    return;
                }

                if (msg.type === "labels_response") {
                    if (msg.success && Array.isArray(msg.labels)) {
                        console.log("Labels response:", msg.labels);
                        setPrompts(msg.labels);
                    } else {
                        console.warn("Label update failed:", msg.message);
                    }
                    return;
                }

                // Handle camera frames
                if (msg.image) {
                    const img = document.getElementById(
                        "jetbot-camera"
                    ) as HTMLImageElement;
                    if (img) img.src = "data:image/jpeg;base64," + msg.image;
                }
            } catch (err) {
                console.warn("Non-JSON WS message:", event.data);
            }
        });

        ws.addEventListener("error", (event) => {
            console.error("WebSocket error:", event);
        });

        ws.addEventListener("close", () => {
            console.log("JetBot WS CLOSED");
            if (wsRef.current === ws) {
                wsRef.current = null;
            }
        });

        return () => {
            if (wsRef.current === ws) {
                wsRef.current = null;
            }
            ws.close();
        };
    }, []);

    const sendLabelsToBackend = (labels: string[]) => {
        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) {
            console.warn("WS not ready, cannot send labels");
            return;
        }

        ws.send(
            JSON.stringify({
                type: "set_labels",
                labels,
            })
        );
    };

    const handleAddPrompt = () => {
        const trimmed = inputValue.trim();
        if (!trimmed) return;

        const newPrompts = [...prompts, trimmed];
        setPrompts(newPrompts);
        setInputValue("");
        sendLabelsToBackend(newPrompts);
    };

    const handleRemovePrompt = (index: number) => {
        const newPrompts = prompts.filter((_, i) => i !== index);
        setPrompts(newPrompts);
        sendLabelsToBackend(newPrompts);
    };

    async function handleEmergencyStop() {
      try {
        await Promise.all([
          fetch(`${JETBOT_API_BASE}/movement/stop`, { method: 'POST' }),
          fetch(`${JETBOT_API_BASE}/rotation/stop`, { method: 'POST' }),
        ]);
      } catch (err) {
        console.error('Error calling emergency stop:', err);
      }
    }

    // WASD control
    useWASDControls({
      linearSpeed,
      angularSpeed,
    });

    return (
        <div className="min-h-screen flex flex-col font-mono bg-black" y-1>
            {/* Top Navigation Bar */}
            <nav className="w-full bg-black border-b border-green-500/30 text-green-500/30 py-2 px-2 flex items-center justify-between">
                <h1 className="text-xl font-semibold text-green-400">
                    Hot Dog Cockpit
                </h1>
                <div className="flex gap-3">
                    <button className="bg-black text-green-400 px-2 py-0.5 rounded font-semibold transition-colors border border-green-500/30 hover:border-green-400">
                        EMERGENCY STOP
                    </button>
                    <button className="bg-black text-green-400 px-2 py-0.5 rounded font-semibold transition-colors border border-green-500/30 hover:border-green-400">
                        RESET SESSION
                    </button>
                </div>
            </nav>

            {/* Main Content Area */}
            <div className="flex-1 flex gap-4 p-4 bg-black">
                {/* Left Side Boxes */}
                <div className="flex flex-col gap-4 flex-1 max-h-[615px]">
                    {/* Box 1 */}
                    <div className="bg-zinc-950 border border-green-500/30 rounded-lg p-4 flex-1 flex flex-col">
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-green-400 text-sm font-semibold">
                                KEYBOARD CONTROLS
                            </h2>
                            <span className="text-green-400 text-xs">
                                ● IDLE
                            </span>
                        </div>

                        {/* Control Grid */}
                        <div className="grid grid-cols-2 gap-3 mb-4">
                            <div className="bg-black border border-green-500/20 rounded p-2 text-green-300 text-xs hover:border-green-500/50 transition-colors">
                                [↑/W] Forward
                            </div>
                            <div className="bg-black border border-green-500/20 rounded p-2 text-green-300 text-xs hover:border-green-500/50 transition-colors">
                                [↓/S] Backward
                            </div>
                            <div className="bg-black border border-green-500/20 rounded p-2 text-green-300 text-xs hover:border-green-500/50 transition-colors">
                                [←/A] Turn Left
                            </div>
                            <div className="bg-black border border-green-500/20 rounded p-2 text-green-300 text-xs hover:border-green-500/50 transition-colors">
                                [→/D] Turn Right
                            </div>
                            <div className="bg-black border border-green-500/20 rounded p-2 text-green-300 text-xs hover:border-green-500/50 transition-colors">
                                [SPACE] Emergency Stop
                            </div>
                            <div className="bg-black border border-green-500/20 rounded p-2 text-green-300 text-xs hover:border-green-500/50 transition-colors">
                                [ESC] Emergency Stop
                            </div>
                        </div>

                        {/* Sliders */}
                        <div className="space-y-3">
                            <div>
                                <label className="text-green-400 text-xs mb-2 block">
                                    LINEAR SPEED (FORWARD/BACKWARD)
                                </label>
                                <div className="flex items-center gap-2">
                                    <input
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.01"
                                        defaultValue="0.5"
                                        className="flex-1 accent-green-500"
                                    />
                                    <span className="text-green-300 text-xs w-12">
                                        0.50
                                    </span>
                                </div>
                            </div>
                            <div>
                                <label className="text-green-400 text-xs mb-2 block">
                                    ANGULAR SPEED (TURNING)
                                </label>
                                <div className="flex items-center gap-2">
                                    <input
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.01"
                                        defaultValue="0.5"
                                        className="flex-1 accent-green-500"
                                    />
                                    <span className="text-green-300 text-xs w-12">
                                        0.50
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Box 2 */}
                    <div className="bg-zinc-950 border border-green-500/30 rounded-lg p-4 flex-1 flex flex-col">
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-green-400 text-sm font-semibold">
                                YOLO PROMPTS
                            </h2>
                            <span className="text-green-400 text-xs">● OK</span>
                        </div>

                        {/* Tags Area */}
                        <div className="flex-1 flex flex-wrap gap-2 mb-4 content-start overflow-y-auto">
                            {prompts.map((prompt, index) => (
                                <div
                                    key={index}
                                    className="bg-black border border-green-500/30 text-green-300 text-xs px-3 py-1 rounded-full flex items-center gap-2"
                                >
                                    {prompt}
                                    <button
                                        onClick={() =>
                                            handleRemovePrompt(index)
                                        }
                                        className="hover:text-red-500 transition-colors"
                                    >
                                        ×
                                    </button>
                                </div>
                            ))}
                        </div>

                        {/* Input Area */}
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={inputValue}
                                onChange={(e) => setInputValue(e.target.value)}
                                onKeyPress={(e) =>
                                    e.key === "Enter" && handleAddPrompt()
                                }
                                placeholder="add a prompt (e.g., red bottle)"
                                className="flex-1 bg-black border border-green-500/30 text-green-300 text-xs px-3 py-2 rounded outline-none placeholder-green-700 focus:border-green-500"
                            />
                            <button
                                onClick={handleAddPrompt}
                                className="bg-green-600 hover:bg-green-700 text-black px-3 py-2 rounded text-xs font-semibold transition-colors"
                            >
                                ✓
                            </button>
                        </div>
                    </div>
                </div>

                {/* Center Camera/Video Feed */}
                <div className="flex items-center justify-center">
                    <img
                        id="jetbot-camera"
                        src="/placeholder.png"
                        className="bg-black w-[700px] h-[615px] rounded-lg object-contain"
                    />
                </div>

                {/* Right Side - Agent Chat */}
                <div className="flex flex-col gap-4 flex-1 max-h-[615px]">
                    <AgentChat />
                </div>
            </div>
        </div>
    );
}
