import { API_BASE, tokenStore } from "./api";
import type { Message, Source } from "@/types";

export interface StreamHandlers {
  onSources?: (payload: { sources: Source[]; warnings: string[] }) => void;
  onToken?: (token: string) => void;
  onFinal?: (msg: Message) => void;
  onError?: (detail: string) => void;
}

/** POSTs a question and parses the Server-Sent Events stream (sources → token* → final). */
export async function streamAnswer(conversationId: string, body: object, h: StreamHandlers, signal?: AbortSignal) {
  const res = await fetch(`${API_BASE}/chat/conversations/${conversationId}/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${tokenStore.get() ?? ""}` },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = `Request failed (${res.status})`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not json */
    }
    h.onError?.(detail);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const event = /^event: (.*)$/m.exec(raw)?.[1];
      const data = /^data: (.*)$/m.exec(raw)?.[1];
      if (!event || data === undefined) continue;
      const payload = JSON.parse(data);
      if (event === "sources") h.onSources?.(payload);
      else if (event === "token") h.onToken?.(payload);
      else if (event === "final") h.onFinal?.(payload);
      else if (event === "error") h.onError?.(payload.detail);
    }
  }
}
