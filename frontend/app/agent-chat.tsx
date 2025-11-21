"use client";

import { KeyboardEvent, useEffect, useRef, useState } from "react";

const ADK_API_URL = "http://localhost:8003";
const APP_NAME = "root_agent";
const USER_ID = "default";

type MessageType = "text" | "tool-call" | "tool-response";

interface Message {
    role: "user" | "agent";
    content: string;
    timestamp: number;
    author?: string;
    type?: MessageType;
    streaming?: boolean;
}

interface FunctionCallPayload {
    name?: string;
    args?: Record<string, unknown>;
}

interface FunctionResponsePayload {
    name?: string;
    response?: unknown;
}

type ToolPart =
    | { kind: "call"; payload: FunctionCallPayload }
    | { kind: "response"; payload: FunctionResponsePayload };

interface SSEPart {
    text?: string;
    functionCall?: FunctionCallPayload;
    functionResponse?: FunctionResponsePayload;
}

interface SSEEvent {
    id?: string;
    author?: string;
    timestamp?: number;
    partial?: boolean;
    content?: {
        parts?: SSEPart[];
    };
}

const AGENT_STYLE_MAP: Record<
    string,
    { bubble: string; label: string; badge: string }
> = {
    DIRECTOR: {
        bubble: "bg-purple-950/70 border border-purple-500/50 text-purple-100",
        label: "text-purple-200",
        badge: "bg-purple-500/30 text-purple-100",
    },
    OBSERVER: {
        bubble: "bg-sky-950/70 border border-sky-500/50 text-sky-100",
        label: "text-sky-200",
        badge: "bg-sky-500/30 text-sky-100",
    },
    PILOT: {
        bubble: "bg-amber-950/70 border border-amber-500/50 text-amber-100",
        label: "text-amber-100",
        badge: "bg-amber-500/30 text-amber-900",
    },
    DEFAULT: {
        bubble: "bg-slate-900 border border-slate-600 text-slate-100",
        label: "text-slate-200",
        badge: "bg-slate-600/40 text-slate-200",
    },
};

const TOOL_STYLE_MAP: Record<MessageType, string> = {
    "tool-call":
        "border-dashed border-emerald-400/60 bg-emerald-950/60 text-emerald-100",
    "tool-response":
        "border border-emerald-500/60 bg-emerald-950/80 text-emerald-100",
    text: "",
};

function getAgentStyles(author?: string, type: MessageType = "text") {
    const key = author?.toUpperCase() || "DEFAULT";
    const palette = AGENT_STYLE_MAP[key] || AGENT_STYLE_MAP.DEFAULT;
    const bubbleClass =
        type === "text"
            ? palette.bubble
            : `${TOOL_STYLE_MAP[type]} text-sm whitespace-pre-wrap`;
    return {
        bubbleClass,
        labelClass: palette.label,
        badgeClass: palette.badge,
    };
}

export default function AgentChat() {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [sessionId, setSessionId] = useState<string | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const streamingTextRef = useRef("");
    const streamingIndexRef = useRef<number | null>(null);
    const hasStreamedRef = useRef(false);
    const currentAuthorRef = useRef<string | null>(null);
    const processedEventsRef = useRef<Set<string>>(new Set());
    const controllerRef = useRef<AbortController | null>(null);

    // Normalize text for comparison (collapse whitespace, remove [AUTHOR] prefix)
    const normalizeTextForComparison = (text: string): string => {
        return text
            .replace(/^\[.*?\]\s*/, "") // Remove [AUTHOR] prefix
            .replace(/\s+/g, " ") // Collapse all whitespace to single spaces
            .trim()
            .toLowerCase(); // Case-insensitive comparison
    };

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    // Cleanup: Clear streaming flags on messages older than 3 seconds
    useEffect(() => {
        const interval = setInterval(() => {
            setMessages((prev) => {
                const now = Date.now();
                const updated = prev.map((msg) => {
                    if (msg.streaming && now - msg.timestamp > 3000) {
                        return { ...msg, streaming: false };
                    }
                    return msg;
                });
                // Only update if something changed
                if (
                    updated.some(
                        (msg, i) => msg.streaming !== prev[i]?.streaming
                    )
                ) {
                    return updated;
                }
                return prev;
            });
        }, 1000); // Check every second

        return () => clearInterval(interval);
    }, []);

    const resetStreamingState = () => {
        streamingTextRef.current = "";
        streamingIndexRef.current = null;
        hasStreamedRef.current = false;
        currentAuthorRef.current = null;
    };

    const appendMessage = (message: Message) => {
        setMessages((prev) => [...prev, message]);
    };

    // Remove all streaming (in-progress) bubbles from state
    const purgeStreamingMessages = () => {
        setMessages((prev) => prev.filter((m) => !m.streaming));
    };

    // Upsert a final (non-streaming) message for an author:
    // - If a streaming bubble exists for the author, finalize/replace that
    // - If a recent message from the same author has similar/duplicate text, replace it
    // - Otherwise, append a new message
    const upsertFinalMessage = (author: string, text: string) => {
        const expectedContent = `[${author}] ${text}`;
        const normalizedNewText = normalizeTextForComparison(text);

        setMessages((prev) => {
            const updated = [...prev];
            let replaced = false;

            // 1) If there is any streaming message from this author, replace it
            for (let i = updated.length - 1; i >= 0; i--) {
                const msg = updated[i];
                if (msg && msg.role === "agent" && msg.author === author) {
                    if (msg.streaming) {
                        updated[i] = {
                            ...msg,
                            streaming: false,
                            content: expectedContent,
                            timestamp: Date.now(),
                        };
                        replaced = true;
                        // Also clear streaming flag on any other bubbles from this author
                        for (let j = 0; j < updated.length; j++) {
                            if (
                                j !== i &&
                                updated[j].author === author &&
                                updated[j].streaming
                            ) {
                                updated[j] = {
                                    ...updated[j],
                                    streaming: false,
                                };
                            }
                        }
                        break;
                    }
                }
            }

            if (replaced) return updated;

            // 2) Try to find a non-streaming message from this author with same/similar text
            for (let i = updated.length - 1; i >= 0; i--) {
                const msg = updated[i];
                if (msg && msg.role === "agent" && msg.author === author) {
                    const normalizedMsgText = normalizeTextForComparison(
                        msg.content
                    );
                    // Equal or subset/superset -> replace older with the new finalized text
                    if (
                        normalizedMsgText === normalizedNewText ||
                        normalizedMsgText.includes(normalizedNewText) ||
                        normalizedNewText.includes(normalizedMsgText)
                    ) {
                        updated[i] = {
                            ...msg,
                            content: expectedContent,
                            streaming: false,
                            timestamp: Date.now(),
                        };
                        replaced = true;
                        break;
                    }
                }
            }

            if (replaced) return updated;

            // 3) No replacement target found -> append a new finalized message
            updated.push({
                role: "agent",
                author,
                content: expectedContent,
                timestamp: Date.now(),
                type: "text",
                streaming: false,
            });
            return updated;
        });
        // After finalizing/upserting, aggressively remove any leftover streaming bubbles
        purgeStreamingMessages();
    };

    const updateStreamingMessage = (author: string, content: string) => {
        setMessages((prev) => {
            const copy = [...prev];
            const existingIndex = streamingIndexRef.current;
            const formatted = `[${author}] ${content}`;

            if (
                existingIndex !== null &&
                copy[existingIndex] &&
                copy[existingIndex].author === author
            ) {
                copy[existingIndex] = {
                    ...copy[existingIndex],
                    content: formatted,
                    streaming: true,
                    timestamp: Date.now(),
                };
                return copy;
            }

            const newIndex = copy.length;
            streamingIndexRef.current = newIndex;
            copy.push({
                role: "agent",
                author,
                content: formatted,
                timestamp: Date.now(),
                type: "text",
                streaming: true,
            });
            return copy;
        });
    };

    const finalizeStreamingMessage = (author?: string, content?: string) => {
        const finalAuthor = author || currentAuthorRef.current;
        if (!finalAuthor) {
            resetStreamingState();
            return;
        }

        setMessages((prev) => {
            const copy = [...prev];
            const idx = streamingIndexRef.current;
            const finalText = content || streamingTextRef.current;
            const finalContent = finalText
                ? `[${finalAuthor}] ${finalText}`
                : null;
            const finalTextOnly = finalText?.trim() || "";

            // First, try to update the streaming message at the tracked index
            if (idx !== null && copy[idx] && copy[idx].author === finalAuthor) {
                copy[idx] = {
                    ...copy[idx],
                    content: finalContent || copy[idx].content,
                    streaming: false,
                    timestamp: Date.now(),
                };
                // Also clear streaming flags on any other messages from this author
                for (let i = 0; i < copy.length; i++) {
                    if (
                        i !== idx &&
                        copy[i].author === finalAuthor &&
                        copy[i].streaming
                    ) {
                        copy[i] = { ...copy[i], streaming: false };
                    }
                }
                return copy;
            }

            // If no tracked index, check if a message with this content already exists
            if (finalTextOnly) {
                const normalizedFinalText =
                    normalizeTextForComparison(finalText);
                for (let i = copy.length - 1; i >= 0; i--) {
                    const msg = copy[i];
                    if (
                        msg &&
                        msg.role === "agent" &&
                        msg.author === finalAuthor
                    ) {
                        const normalizedMsgText = normalizeTextForComparison(
                            msg.content
                        );
                        if (normalizedMsgText === normalizedFinalText) {
                            // Update existing message to clear streaming
                            copy[i] = {
                                ...msg,
                                content: finalContent || msg.content,
                                streaming: false,
                                timestamp: Date.now(),
                            };
                            // Clear streaming flags on other messages from this author
                            for (let j = 0; j < copy.length; j++) {
                                if (
                                    j !== i &&
                                    copy[j].author === finalAuthor &&
                                    copy[j].streaming
                                ) {
                                    copy[j] = { ...copy[j], streaming: false };
                                }
                            }
                            return copy;
                        }
                    }
                }
            }

            // Only create new message if we have content and no duplicate exists
            if (finalContent) {
                copy.push({
                    role: "agent",
                    author: finalAuthor,
                    content: finalContent,
                    timestamp: Date.now(),
                    type: "text",
                    streaming: false,
                });
            }
            return copy;
        });

        // After finalization, aggressively remove any leftover streaming bubbles
        purgeStreamingMessages();
        resetStreamingState();
    };

    const appendToolBlurb = (author: string, tool: ToolPart) => {
        if (tool.kind === "call") {
            const name = tool.payload?.name || "unknown";
            const detail = tool.payload?.args ?? {};
            const prettyDetail = JSON.stringify(detail, null, 2);
            appendMessage({
                role: "agent",
                author,
                type: "tool-call",
                content: `[${author}] Tool Call → ${name}\n${prettyDetail}`,
                timestamp: Date.now(),
            });
            return;
        }

        const name = tool.payload?.name || "unknown";
        const detail = tool.payload?.response ?? {};
        const prettyDetail = JSON.stringify(detail, null, 2);
        appendMessage({
            role: "agent",
            author,
            type: "tool-response",
            content: `[${author}] Tool Result ← ${name}\n${prettyDetail}`,
            timestamp: Date.now(),
        });
    };

    const handleSSEvent = (event: SSEEvent) => {
        if (!event) return;

        const key = JSON.stringify({
            id: event.id,
            author: event.author,
            timestamp: event.timestamp,
            content: event.content,
            partial: event.partial,
        });

        if (processedEventsRef.current.has(key)) {
            return;
        }
        processedEventsRef.current.add(key);
        if (processedEventsRef.current.size > 200) {
            const iterator = processedEventsRef.current.values().next();
            const first = iterator.value;
            if (first) {
                processedEventsRef.current.delete(first);
            }
        }

        const author = String(event.author || "agent").toUpperCase();
        const parts = Array.isArray(event.content?.parts)
            ? (event.content.parts as SSEPart[])
            : [];
        const textParts: string[] = [];
        const toolParts: ToolPart[] = [];

        for (const part of parts) {
            if (typeof part?.text === "string" && part.text.trim()) {
                textParts.push(part.text);
            }
            if (part?.functionCall) {
                toolParts.push({ kind: "call", payload: part.functionCall });
            }
            if (part?.functionResponse) {
                toolParts.push({
                    kind: "response",
                    payload: part.functionResponse,
                });
            }
        }

        // Only show tool calls, not tool results
        toolParts
            .filter((tool) => tool.kind === "call")
            .forEach((tool) => appendToolBlurb(author, tool));

        const joined = textParts.join("");

        const switchAuthors =
            !event.partial &&
            hasStreamedRef.current &&
            currentAuthorRef.current &&
            currentAuthorRef.current !== author &&
            streamingTextRef.current;

        if (switchAuthors) {
            finalizeStreamingMessage(
                currentAuthorRef.current || undefined,
                streamingTextRef.current
            );
        }

        if (event.partial) {
            const changingAuthor =
                hasStreamedRef.current &&
                currentAuthorRef.current &&
                currentAuthorRef.current !== author &&
                streamingTextRef.current;

            if (changingAuthor) {
                finalizeStreamingMessage(
                    currentAuthorRef.current || undefined,
                    streamingTextRef.current
                );
            }

            currentAuthorRef.current = author;
            hasStreamedRef.current = true;

            if (joined) {
                streamingTextRef.current =
                    currentAuthorRef.current === author &&
                    streamingTextRef.current
                        ? streamingTextRef.current + joined
                        : joined;
                updateStreamingMessage(author, streamingTextRef.current);
            }
            return;
        }

        if (hasStreamedRef.current && currentAuthorRef.current === author) {
            if (joined) {
                streamingTextRef.current += joined;
            }
            finalizeStreamingMessage(
                author,
                streamingTextRef.current || joined
            );
            return;
        }

        // Upsert a finalized message, merging with any streaming or similar prior content
        if (joined) {
            upsertFinalMessage(author, joined);
            return;
        }

        if (!joined && toolParts.length === 0) {
            finalizeStreamingMessage(author);
        }
    };

    const startSessionIfNeeded = async (): Promise<string> => {
        if (sessionId) return sessionId;

        const sessionResp = await fetch(
            `${ADK_API_URL}/apps/${APP_NAME}/users/${USER_ID}/sessions`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            }
        );

        if (!sessionResp.ok) {
            throw new Error(`Failed to create session: ${sessionResp.status}`);
        }

        const sessionData = await sessionResp.json();
        const newId: string | undefined =
            sessionData.id || sessionData.session_id;
        if (!newId) {
            throw new Error("ADK session response did not include an id");
        }
        setSessionId(newId);
        return newId;
    };

    const streamAgentResponse = async (
        currentSessionId: string,
        prompt: string
    ): Promise<void> => {
        controllerRef.current?.abort();
        const controller = new AbortController();
        controllerRef.current = controller;

        const response = await fetch(`${ADK_API_URL}/run_sse`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            signal: controller.signal,
            body: JSON.stringify({
                app_name: APP_NAME,
                user_id: USER_ID,
                session_id: currentSessionId,
                new_message: {
                    role: "user",
                    parts: [{ text: prompt }],
                },
                streaming: true,
            }),
        });

        if (!response.ok || !response.body) {
            const errorText = await response.text();
            throw new Error(
                `ADK SSE error ${response.status}: ${errorText || "no body"}`
            );
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const rawLine of lines) {
                const line = rawLine.trim();
                if (!line) continue;
                if (line === "[DONE]" || line === "data: [DONE]") {
                    finalizeStreamingMessage();
                    continue;
                }

                const payload = line.startsWith("data:")
                    ? line.slice(5).trim()
                    : line;
                if (!payload) continue;

                try {
                    const parsed = JSON.parse(payload) as SSEEvent;
                    handleSSEvent(parsed);
                } catch (err) {
                    console.warn("Failed to parse SSE payload:", payload, err);
                }
            }
        }

        if (buffer.trim() && buffer.trim() !== "[DONE]") {
            try {
                const parsed = JSON.parse(
                    buffer.startsWith("data:")
                        ? buffer.slice(5).trim()
                        : buffer.trim()
                ) as SSEEvent;
                handleSSEvent(parsed);
            } catch {
                // ignore final partial parse errors
            }
        }

        finalizeStreamingMessage();
    };

    const sendMessage = async () => {
        if (!input.trim() || isLoading) return;

        const text = input.trim();

        const userMessage: Message = {
            role: "user",
            content: text,
            timestamp: Date.now(),
        };

        setMessages((prev) => [...prev, userMessage]);
        setInput("");
        setIsLoading(true);
        processedEventsRef.current.clear();
        resetStreamingState();

        try {
            const currentSessionId = await startSessionIfNeeded();
            await streamAgentResponse(currentSessionId, text);
        } catch (error) {
            if ((error as Error).name === "AbortError") {
                return;
            }
            console.error("Error sending message:", error);
            appendMessage({
                role: "agent",
                content: `Error: ${
                    error instanceof Error
                        ? error.message
                        : "Failed to communicate with agent"
                }`,
                timestamp: Date.now(),
            });
        } finally {
            setIsLoading(false);
        }
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    const clearChat = () => {
        controllerRef.current?.abort();
        setMessages([]);
        setSessionId(null);
        processedEventsRef.current.clear();
        resetStreamingState();
    };

    return (
        <div className="flex flex-col h-screen bg-zinc-950 border border-green-500/30 rounded-lg">
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-green-500/30">
                <h2 className="text-green-400 text-sm font-semibold">
                    AGENT CHAT
                </h2>
                <div className="flex items-center gap-2 text-xs">
                    <span className="text-green-400">
                        {sessionId ? "● CONNECTED" : "○ NO SESSION"}
                    </span>
                    {sessionId && (
                        <button
                            onClick={clearChat}
                            className="text-green-400 hover:text-red-400 transition-colors"
                        >
                            [CLEAR]
                        </button>
                    )}
                </div>
            </div>

            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-linear-to-b from-black via-zinc-950 to-black">
                {messages.length === 0 && (
                    <div className="text-green-500/50 text-xs text-center py-8">
                        Type a command to start the mission...
                    </div>
                )}

                {messages.map((msg, index) => {
                    if (msg.role === "user") {
                        return (
                            <div key={index} className="flex justify-end">
                                <div className="max-w-[80%] rounded-lg p-3 bg-green-600 text-black shadow-md">
                                    <div className="text-xs font-semibold mb-1">
                                        USER
                                    </div>
                                    <div className="text-sm whitespace-pre-wrap">
                                        {msg.content}
                                    </div>
                                </div>
                            </div>
                        );
                    }

                    const { bubbleClass, labelClass, badgeClass } =
                        getAgentStyles(msg.author, msg.type || "text");
                    const labelText =
                        msg.type === "tool-call"
                            ? `${msg.author || "AGENT"} · TOOL CALL`
                            : msg.type === "tool-response"
                            ? `${msg.author || "AGENT"} · TOOL RESULT`
                            : `${msg.author || "AGENT"}`;

                    return (
                        <div key={index} className="flex justify-start">
                            <div
                                className={`max-w-[85%] rounded-lg p-3 transition-all shadow-md ${
                                    msg.streaming ? "animate-pulse" : ""
                                } ${bubbleClass}`}
                            >
                                <div
                                    className={`flex items-center gap-2 text-xs font-semibold mb-1 ${labelClass}`}
                                >
                                    <span
                                        className={`px-2 py-0.5 rounded-full ${badgeClass}`}
                                    >
                                        {labelText}
                                    </span>
                                    {msg.streaming && (
                                        <span className="text-[10px] uppercase tracking-wide">
                                            streaming...
                                        </span>
                                    )}
                                </div>
                                <div className="text-sm whitespace-pre-wrap">
                                    {msg.content}
                                </div>
                            </div>
                        </div>
                    );
                })}

                {isLoading && (
                    <div className="flex justify-start">
                        <div className="rounded-lg p-3 bg-black border border-green-500/30 text-green-200 text-sm">
                            <span className="animate-pulse">Processing...</span>
                        </div>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="border-t border-green-500/30 p-4 bg-black">
                <div className="flex gap-2">
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="Command the robot..."
                        disabled={isLoading}
                        className="flex-1 bg-zinc-900 border border-green-500/30 text-green-300 text-sm px-3 py-2 rounded outline-none placeholder-green-700 focus:border-green-500 disabled:opacity-50"
                    />
                    <button
                        onClick={sendMessage}
                        disabled={!input.trim() || isLoading}
                        className="bg-green-600 hover:bg-green-700 disabled:bg-green-900 disabled:text-green-700 text-black px-4 py-2 rounded text-sm font-semibold transition-colors"
                    >
                        {isLoading ? "..." : "SEND"}
                    </button>
                </div>
                <div className="text-green-500/50 text-xs mt-2">
                    Examples: &ldquo;find a bottle&rdquo;, &ldquo;scan the
                    room&rdquo;, &ldquo;move forward 0.5m&rdquo;
                </div>
            </div>
        </div>
    );
}
