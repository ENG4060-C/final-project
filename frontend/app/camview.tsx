"use client"

import React, { useEffect, useRef, useState } from "react";

type CamViewProps = {
    facingMode?: "user" | "environment"; // front or back camera
    width?: number;
    height?: number;
    onCapture?: (blob: Blob) => void;    // callback with captured image
};

export default function CamView({
    facingMode = "user",
    width = 640,
    height = 480,
    onCapture,
}: CamViewProps) {
    const videoRef = useRef<HTMLVideoElement | null>(null);
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const [stream, setStream] = useState<MediaStream | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let mounted = true;
        async function startCamera() {
            setLoading(true);
            setError(null);
            try {
                const s = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode },
                    audio: false,
                });
                if (!mounted) {
                    // If component unmounted while awaiting permission, stop tracks
                    s.getTracks().forEach((t) => t.stop());
                    return;
                }
                setStream(s);
                if (videoRef.current) videoRef.current.srcObject = s;
            } catch (err) {
                setError((err as Error).message || "Failed to access camera");
            } finally {
                if (mounted) setLoading(false);
            }
        }
        startCamera();

        return () => {
            mounted = false;
            if (stream) {
                stream.getTracks().forEach((track) => track.stop());
            }
        };
    }, [facingMode]); // restart if facingMode changes

    function capture() {
        const video = videoRef.current;
        const canvas = canvasRef.current;
        if (!video || !canvas) return;
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(video, 0, 0, width, height);
        canvas.toBlob((blob) => {
            if (!blob) return;
            onCapture?.(blob);
            // Example: open captured image in new tab
            const url = URL.createObjectURL(blob);
            window.open(url, "_blank");
            // Cleanup object URL after short time
            setTimeout(() => URL.revokeObjectURL(url), 5000);
        }, "image/png");
    }

    return (
        <div>
            {loading && <p>Starting camera…</p>}
            {error && <p style={{ color: "red" }}>Error: {error}</p>}
            <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                width={width}
                height={height}
                style={{ background: "#000" }}
            />
            <div style={{ marginTop: 8 }}>
                <button onClick={capture} disabled={!!error || loading}>
                    Capture
                </button>
            </div>
            {/* Hidden canvas used to produce image data */}
            <canvas ref={canvasRef} style={{ display: "none" }} />
        </div>
    );
}