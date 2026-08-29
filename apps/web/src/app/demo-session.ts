export type DemoSessionInfo = {
  session_id: string;
  expires_at: string;
  remaining_mutations: number;
};

export async function ensureDemoSession(): Promise<DemoSessionInfo> {
  const response = await fetch("/api/demo/session", {
    method: "POST",
    headers: { "X-Request-ID": crypto.randomUUID() },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Judge session could not start (${response.status}).`);
  }
  return (await response.json()) as DemoSessionInfo;
}
