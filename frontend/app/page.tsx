'use client';

import { useEffect, useRef, useState } from 'react';
import Image from 'next/image'

export default function Home() {
  const [prompts, setPrompts] = useState<string[]>(['person']);
  const [inputValue, setInputValue] = useState('');

  // Camera fram from YOLOE
  const [frame, setFrame] = useState<string | null>(null);

  // Motor telemetry - sliders (read only)
  const [linearVelocity, setLinearVelocity] = useState(0);
  const [angularVelocity, setAngularVelocity] = useState(0);

  // Websocket connection
  const wsRef = useRef<WebSocket | null>(null);

  // --- WebSocket ---
  useEffect(() => {
    console.log("Connecting to JetBot WebSocket…");

    const ws = new WebSocket('ws://localhost:8002/ws/telemetry?client=frontend');
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("JetBot WS CONNECTED");
    };


    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);

        // Label events
        if (msg.type === 'event' && msg.event_type === 'labels_updated') {
          const labels = msg.data?.labels;
          if (Array.isArray(labels)) {
            console.log('Labels updated from backend:', labels);
            setPrompts(labels);
          }
          return;
        }

        if (msg.type === 'labels_response') {
          if (msg.success && Array.isArray(msg.labels)) {
            console.log('Labels response:', msg.labels);
            setPrompts(msg.labels);
          }
          else {
            console.warn('Label update failed:', msg.message);
          }
          return;
        }

        // Telemetry frames
        if (msg.image) {
          setFrame(msg.image);
        }

        if (msg.motors) {
          const left = msg.motors.left ?? 0;
          const right = msg.motors.right ?? 0;

          const newLinear = (left + right) / 2;
          const newAngular = (right - left) / 2;

          setLinearVelocity(parseFloat(newLinear.toFixed(2)));
          setAngularVelocity(parseFloat(newAngular.toFixed(2)));
        }
      } catch (err) {
        console.warn('Non-JSON or bad WS message:', event.data);
      }
    };

    ws.onerror = (ev) => {
      console.error('WebSocket error:', ev);
    };

    ws.onclose = () => {
      console.log('WS CLOSED');
      if (wsRef.current === ws) {
        wsRef.current = null;
      }
    };

    return () => {
      if (wsRef.current === ws) {
        wsRef.current = null;
      }
      ws.close();
    };
  }, []);

  // Helpers
  function sendLabelsToBackend(labels: string[]) {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      console.warn('WS not ready, cannot send labels');
      return;
    }

    ws.send(
      JSON.stringify({
        type: 'set_labels',
        labels,
      })
    );
  }

  // Prompt handlers
  const handleAddPrompt = () => {
    const trimmed = inputValue.trim();
    if (!trimmed) return;

    const newPrompts = [...prompts, trimmed];
    setPrompts(newPrompts);
    setInputValue('');
    sendLabelsToBackend(newPrompts);
  };

  const handleRemovePrompt = (index: number) => {
    const newPrompts = prompts.filter((_, i) => i !== index);
    setPrompts(newPrompts);
    sendLabelsToBackend(newPrompts);
  };

  // Camera src (JetBot frame or placeholder)
  const cameraSrc = frame
    ? `data:image/jpeg;base64,${frame}`
    : '/placeholder.png';

  return (
    <div className="min-h-screen flex flex-col font-mono bg-black">
      {/* Top Navigation Bar */}
      <nav className="w-full bg-black border-b border-green-500/30 text-green-500/30 py-2 px-2 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-green-400">Hot Dog Cockpit</h1>
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
              <h2 className="text-green-400 text-sm font-semibold">KEYBOARD CONTROLS</h2>
              <span className="text-green-400 text-xs">● IDLE</span>
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

            {/* Sliders (read-only telemetry) */}
            <div className="space-y-3">
              <div>
                <label className="text-green-400 text-xs mb-2 block">
                  LINEAR SPEED (FORWARD/BACKWARD)
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min={-1}
                    max={1}
                    step={0.01}
                    value={linearVelocity}
                    readOnly
                    className="flex-1 accent-green-500"
                  />
                  <span className="text-green-300 text-xs w-12">
                    {linearVelocity.toFixed(2)}
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
                    min={-1}
                    max={1}
                    step={0.01}
                    value={angularVelocity}
                    readOnly
                    className="flex-1 accent-green-500"
                  />
                  <span className="text-green-300 text-xs w-12">
                    {angularVelocity.toFixed(2)}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Box 2 */}
          <div className="bg-zinc-950 border border-green-500/30 rounded-lg p-4 flex-1 flex flex-col">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-green-400 text-sm font-semibold">YOLO PROMPTS</h2>
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
                    onClick={() => handleRemovePrompt(index)}
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
                onKeyDown={(e) => e.key === 'Enter' && handleAddPrompt()}
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
            src={cameraSrc}
            className="bg-black w-[700px] h-[615px] rounded-lg object-contain"
            alt="JetBot camera"
          />
        </div>

        {/* Right Side Boxes */}
        <div className="flex flex-col gap-4 flex-1 max-h-[615px]">
          <div className="bg-zinc-950 border border-green-500/30 rounded-lg p-4 flex-1 flex items-center justify-center overflow-hidden">
            <Image
              src="/hacker.gif"
              alt="Hacker GIF"
              width={400}
              height={300}
              unoptimized
              className="w-full h-full object-cover rounded"
            />
          </div>
          <div className="bg-zinc-950 border border-green-500/30 rounded-lg p-4 flex-1 flex flex-col">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-green-400 text-sm font-semibold">SUBTITLES</h2>
            </div>
            <div className="flex-1 overflow-y-auto">
              {/* Subtitles content will go here */}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}