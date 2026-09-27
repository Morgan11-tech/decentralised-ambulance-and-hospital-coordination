// The Vite dev server proxies /api and /ws to the FastAPI backend (vite.config.ts),
// so the browser never needs to know the backend address or any API keys.

export async function createSession(): Promise<string> {
  let response: Response;
  try {
    response = await fetch("/api/session", { method: "POST" });
  } catch {
    throw new Error("Cannot reach the backend. Is it running on port 8000?");
  }
  if (!response.ok) throw new Error(`Backend error ${response.status} while creating a session.`);
  const body = (await response.json()) as { session_id: string };
  return body.session_id;
}

export function voiceSocketUrl(sessionId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/ws/voice/${sessionId}`;
}
