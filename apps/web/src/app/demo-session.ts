export type DemoSessionInfo = {
  session_id: string;
  expires_at: string;
  remaining_mutations: number;
};

export async function ensureDemoSession(): Promise<DemoSessionInfo> {
  let lastStatus = 503;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const response = await fetch("/api/demo/session", {
      method: "POST",
      headers: { "X-Request-ID": crypto.randomUUID() },
      cache: "no-store",
    });
    if (response.ok) return (await response.json()) as DemoSessionInfo;
    lastStatus = response.status;
    if (response.status < 500 || attempt === 2) break;
    await delay(500 * (attempt + 1));
  }
  throw new Error(`Secure recovery session could not start (${lastStatus}). Try again.`);
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
