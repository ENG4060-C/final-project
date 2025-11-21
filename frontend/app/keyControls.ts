"use client";

import { useEffect } from 'react';

const JETBOT_API_BASE = 'http://localhost:8000';

export interface WASDOptions {
  linearSpeed: number;
  angularSpeed: number;
}

async function postJSON(path: string, body?: any) {
  try {
    await fetch(`${JETBOT_API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    console.error(`Error calling ${path}:`, err);
  }
}

export function useWASDControls({ linearSpeed, angularSpeed }: WASDOptions) {
  useEffect(() => {
    let movementActive = false;
    let rotationActive = false;

    const isTypingTarget = (target: EventTarget | null): boolean => {
      const el = target as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName;
      return (
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        (el as HTMLElement).isContentEditable === true
      );
    };

    const startMovement = async (speed: number) => {
      movementActive = true;
      await postJSON('/movement/start', { robot_speed: speed });
    };

    const stopMovement = async () => {
      if (!movementActive) return;
      movementActive = false;
      await postJSON('/movement/stop');
    };

    const startRotation = async (direction: number) => {
      rotationActive = true;
      const speed = Math.max(0.3, Math.min(1.0, angularSpeed || 0.4));
      await postJSON('/rotation/start', {
        robot_speed: speed,
        direction,
      });
    };

    const stopRotation = async () => {
      if (!rotationActive) return;
      rotationActive = false;
      await postJSON('/rotation/stop');
    };

    const emergencyStop = async () => {
      await Promise.all([stopMovement(), stopRotation()]);
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;
      if (e.repeat) return;

      switch (e.key) {
        case 'w':
        case 'ArrowUp': {
          const mag = Math.max(0, Math.min(1, linearSpeed || 0.5));
          void startMovement(+mag); // forward
          break;
        }
        case 's':
        case 'ArrowDown': {
          const mag = Math.max(0, Math.min(1, linearSpeed || 0.5));
          void startMovement(-mag); // backward
          break;
        }
        case 'a':
        case 'ArrowLeft':
          void startRotation(-1); // left
          break;
        case 'd':
        case 'ArrowRight':
          void startRotation(1); // right
          break;
        case ' ':
        case 'Escape':
          void emergencyStop();
          break;
        default:
          break;
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;

      switch (e.key) {
        case 'w':
        case 'ArrowUp':
        case 's':
        case 'ArrowDown':
          void stopMovement();
          break;
        case 'a':
        case 'ArrowLeft':
        case 'd':
        case 'ArrowRight':
          void stopRotation();
          break;
        default:
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      void emergencyStop();
    };
  }, [linearSpeed, angularSpeed]);
}
