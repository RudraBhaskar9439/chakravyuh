import { createHmac, randomUUID, timingSafeEqual } from "node:crypto";

export const demoSessionCookieName = "chakravyuh_judge_session";
export const demoSessionTtlSeconds = 30 * 60;
export const demoSessionMutationLimit = 24;

export type DemoSession = {
  version: 1;
  sessionId: string;
  issuedAt: number;
  expiresAt: number;
  mutationCount: number;
  orderIds: string[];
  paymentIds: string[];
  incidentIds: string[];
  proposalIds: string[];
};

export function createDemoSession(now = Date.now()): DemoSession {
  return {
    version: 1,
    sessionId: randomUUID(),
    issuedAt: now,
    expiresAt: now + demoSessionTtlSeconds * 1000,
    mutationCount: 0,
    orderIds: [],
    paymentIds: [],
    incidentIds: [],
    proposalIds: [],
  };
}

export function readDemoSession(request: Request, secret: string): DemoSession | null {
  const cookie = request.headers
    .get("Cookie")
    ?.split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${demoSessionCookieName}=`));
  if (!cookie) return null;
  const token = cookie.slice(demoSessionCookieName.length + 1);
  const separator = token.lastIndexOf(".");
  if (separator < 1) return null;
  const encoded = token.slice(0, separator);
  const signature = token.slice(separator + 1);
  const expected = sign(encoded, secret);
  if (!safeEqual(signature, expected)) return null;
  try {
    const candidate = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8")) as unknown;
    return isDemoSession(candidate) && candidate.expiresAt > Date.now() ? candidate : null;
  } catch {
    return null;
  }
}

export function writeDemoSession(headers: Headers, session: DemoSession, secret: string): void {
  const encoded = Buffer.from(JSON.stringify(session)).toString("base64url");
  const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
  headers.append(
    "Set-Cookie",
    `${demoSessionCookieName}=${encoded}.${sign(encoded, secret)}; Path=/api/demo; HttpOnly; SameSite=Strict; Max-Age=${demoSessionTtlSeconds}${secure}`,
  );
}

export function evolveDemoSession(
  session: DemoSession,
  additions: Partial<
    Pick<DemoSession, "orderIds" | "paymentIds" | "incidentIds" | "proposalIds">
  > = {},
): DemoSession {
  return {
    ...session,
    mutationCount: session.mutationCount + 1,
    orderIds: mergeIds(session.orderIds, additions.orderIds),
    paymentIds: mergeIds(session.paymentIds, additions.paymentIds),
    incidentIds: mergeIds(session.incidentIds, additions.incidentIds),
    proposalIds: mergeIds(session.proposalIds, additions.proposalIds),
  };
}

export function getDemoSessionSecret(): string | null {
  return (
    process.env.CHAKRAVYUH_DEMO_SESSION_SECRET ?? process.env.CHAKRAVYUH_DEMO_MAKER_TOKEN ?? null
  );
}

function mergeIds(existing: string[], additions: string[] | undefined): string[] {
  return [...new Set([...existing, ...(additions ?? [])])].slice(-8);
}

function sign(encoded: string, secret: string): string {
  return createHmac("sha256", secret).update(encoded).digest("base64url");
}

function safeEqual(left: string, right: string): boolean {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer);
}

function isDemoSession(candidate: unknown): candidate is DemoSession {
  if (!candidate || typeof candidate !== "object") return false;
  const value = candidate as Partial<DemoSession>;
  return (
    value.version === 1 &&
    typeof value.sessionId === "string" &&
    typeof value.issuedAt === "number" &&
    typeof value.expiresAt === "number" &&
    typeof value.mutationCount === "number" &&
    isStringArray(value.orderIds) &&
    isStringArray(value.paymentIds) &&
    isStringArray(value.incidentIds) &&
    isStringArray(value.proposalIds)
  );
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}
