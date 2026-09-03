import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Platform Overview · Chakravyuh",
  description: "How Chakravyuh detects, governs, and verifies payment recovery",
};

const steps = [
  {
    number: "01",
    eyebrow: "Create evidence",
    title: "Fail one ₹10 Test Mode payment",
    copy: "Razorpay returns the authoritative failed state. Chakravyuh stores only allowlisted money facts and their content hashes.",
    action: "Start failed-payment recovery",
    href: "/payments/recover-failure?tour=1",
    proof: "Provider payment ID · state · amount · verification hash",
  },
  {
    number: "02",
    eyebrow: "Understand the break",
    title: "Watch the graph isolate one violated invariant",
    copy: "The temporal journey connects order, payment, webhook and invariant evidence. AI explains the bounded subgraph; deterministic rules retain authority.",
    action: "Open Money Trace",
    href: "/trace",
    proof: "Connected citations · deterministic finding · append-only revision",
  },
  {
    number: "03",
    eyebrow: "Recover safely",
    title: "Create one expiring provider-hosted recovery path",
    copy: "Policy checks the exact target and amount, an independent checker approves, and the mutation checkpoint prevents a duplicate link after an ambiguous timeout.",
    action: "Inspect verified recoveries",
    href: "/recoveries/verified",
    proof: "Policy decision · checker identity · provider receipt · audit root",
  },
  {
    number: "04",
    eyebrow: "Verify the outcome",
    title: "Separate a successful request from recovered revenue",
    copy: "Only a signed payment_link.paid webhook resolves the incident. The sealed arenas expose unsafe baselines, duplicate delivery, provider faults and uncredited outcomes.",
    action: "Open reliability report",
    href: "/reliability",
    proof: "10,005 journeys · 8 link faults · 0 duplicate mutations",
  },
] as const;

export default function WalkthroughPage() {
  return (
    <main className="walkthroughShell">
      <header className="walkthroughHero">
        <div>
          <p className="eyebrow">Platform overview</p>
          <h1>From payment failure to verified recovery.</h1>
        </div>
        <div className="walkthroughIntro">
          <p>
            Follow this route once. It moves from a real Razorpay Test Mode failure to a bounded
            recovery, then lets you independently inspect the provider state and sealed evidence.
          </p>
          <a href="/payments/recover-failure?tour=1">
            Begin with a ₹10 failure <span aria-hidden="true">→</span>
          </a>
        </div>
      </header>

      <section className="walkthroughSteps" aria-label="Recovery control stages">
        {steps.map((step) => (
          <article key={step.number}>
            <span className="walkthroughNumber">{step.number}</span>
            <div>
              <p>{step.eyebrow}</p>
              <h2>{step.title}</h2>
              <p>{step.copy}</p>
            </div>
            <aside>
              <small>Evidence to look for</small>
              <strong>{step.proof}</strong>
              <a href={step.href}>{step.action} →</a>
            </aside>
          </article>
        ))}
      </section>

      <section className="walkthroughBoundary">
        <p className="eyebrow">Evidence boundary</p>
        <h2>Measured proof with explicit operational limits.</h2>
        <div>
          <article>
            <span>Measured proof</span>
            <p>
              Real Razorpay Test Mode semantics, production control flow, deterministic replay,
              bounded provider mutation and reproducible synthetic scale measurements.
            </p>
          </article>
          <article>
            <span>Operational limits</span>
            <p>
              Live customer funds, merchant conversion lift, a production SLA, or external design
              partner validation. Those require a governed merchant pilot.
            </p>
          </article>
        </div>
      </section>
    </main>
  );
}
