"use client";

import { useState } from "react";

export default function Motor() {
    const [left, setLeft] = useState(0);
    const [right, setRight] = useState(0);

    return (
        <div className="flex flex-col h-full justify-center">
            {/* Title */}
            <div className="text-center font-semibold text-gray-700 mb-2">
                Motor Control
            </div>

            {/* Sliders */}
            <div className="flex-1 flex flex-col gap-4 justify-center">

                {/* Left Motor */}
                <div>
                    <div className="text-gray-700 text-sm font-medium mb-1">
                        Left Motor
                    </div>
                    <input
                        type="range"
                        min={-1}
                        max={1}
                        step={0.01}
                        value={left}
                        onChange={(e) => setLeft(parseFloat(e.target.value))}
                        className="w-full"
                    />
                    <div className="text-xs text-gray-600 mt-1">
                        {left.toFixed(2)}
                    </div>
                </div>

                {/* Right Motor */}
                <div>
                    <div className="text-gray-700 text-sm font-medium mb-1">
                        Right Motor
                    </div>
                    <input
                        type="range"
                        min={-1}
                        max={1}
                        step={0.01}
                        value={right}
                        onChange={(e) => setRight(parseFloat(e.target.value))}
                        className="w-full"
                    />
                    <div className="text-xs text-gray-600 mt-1">
                        {right.toFixed(2)}
                    </div>
                </div>

            </div>
        </div>
    )
}