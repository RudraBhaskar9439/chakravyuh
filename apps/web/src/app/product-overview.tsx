const recoveryStages = [
  {
    number: "01",
    title: "Detect",
    detail: "Deterministic rules identify broken payment lifecycles.",
  },
  {
    number: "02",
    title: "Explain",
    detail: "AI summarizes a bounded, cited evidence graph.",
  },
  {
    number: "03",
    title: "Govern",
    detail: "Policy and independent approval constrain the action.",
  },
  {
    number: "04",
    title: "Confirm",
    detail: "Provider state—not an internal success flag—closes recovery.",
  },
] as const;

const platformCapabilities = [
  {
    label: "Money Trace",
    title: "Trace every payment decision",
    copy: "Resolve a payment, order, incident, or evidence hash into one connected money journey.",
    href: "/trace",
    action: "Search transactions",
  },
  {
    label: "Verification",
    title: "Re-query the provider",
    copy: "Compare the original authorization with a fresh Razorpay state and its immutable receipt.",
    href: "/recoveries/verified",
    action: "Open verification ledger",
  },
  {
    label: "Reliability",
    title: "Inspect measured controls",
    copy: "Review held-out recovery results, provider faults, duplicate protection, and sealed hashes.",
    href: "/reliability",
    action: "View reliability report",
  },
] as const;

export function ProductOverview() {
  return (
    <main className="productOverview">
      <section className="productHero">
        <div className="productHeroCopy">
          <p className="eyebrow">Payment recovery control plane</p>
          <h1>
            Recover revenue.
            <span> Keep every action under control.</span>
          </h1>
          <p className="productHeroSummary">
            Chakravyuh connects payment events, evidence, policy, and provider state so operations
            teams can recover broken payments without giving AI authority over money.
          </p>
          <div className="productHeroActions">
            <a className="productPrimaryAction" href="/payments/authorize">
              Start a recovery <span aria-hidden="true">→</span>
            </a>
            <a className="productSecondaryAction" href="/recoveries/verified">
              View verified transaction
            </a>
          </div>
          <ul className="productTrustLine" aria-label="Environment safeguards">
            <li>Razorpay Test Mode</li>
            <li>Provider-backed verification</li>
            <li>Server-side credentials</li>
          </ul>
        </div>

        <aside className="controlLoop" aria-label="Recovery control loop">
          <header>
            <div>
              <p>Recovery control loop</p>
              <strong>Evidence before action</strong>
            </div>
            <span className="controlLoopStatus">
              <i aria-hidden="true" /> Policy enforced
            </span>
          </header>
          <ol>
            {recoveryStages.map((stage) => (
              <li key={stage.number}>
                <span>{stage.number}</span>
                <div>
                  <strong>{stage.title}</strong>
                  <p>{stage.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </aside>
      </section>

      <section className="productMetrics" aria-label="Measured platform evidence">
        <article>
          <strong>10,005</strong>
          <span>held-out payment journeys</span>
        </article>
        <article>
          <strong>0</strong>
          <span>incorrect policy-approved actions</span>
        </article>
        <article>
          <strong>0</strong>
          <span>duplicate provider mutations</span>
        </article>
        <article>
          <strong>203</strong>
          <span>provider-confirmed recoveries</span>
        </article>
      </section>

      <section className="recoveryWorkflows" aria-labelledby="recovery-workflows-title">
        <header>
          <div>
            <p className="eyebrow">Recovery workflows</p>
            <h2 id="recovery-workflows-title">Choose where the payment stopped.</h2>
          </div>
          <p>
            Both workflows use the same deterministic detection, evidence graph, policy boundary,
            independent approval, and provider confirmation.
          </p>
        </header>
        <div>
          <article>
            <span>Authorization recovery</span>
            <h3>Authorized, but never captured</h3>
            <p>
              Identify an authorization outside its capture window and execute one exact,
              amount-bound Razorpay capture.
            </p>
            <a href="/payments/authorize">Recover an authorization →</a>
          </article>
          <article>
            <span>Payment failure recovery</span>
            <h3>Failed before conversion</h3>
            <p>
              Verify the failed payment, create one expiring Payment Link, and credit recovery only
              after provider confirmation.
            </p>
            <a href="/payments/recover-failure">Recover a failed payment →</a>
          </article>
        </div>
      </section>

      <section className="platformSection" aria-labelledby="platform-capabilities-title">
        <header>
          <p className="eyebrow">Operations platform</p>
          <h2 id="platform-capabilities-title">One system of record for recovery.</h2>
        </header>
        <div className="platformGrid">
          {platformCapabilities.map((capability) => (
            <a href={capability.href} key={capability.label}>
              <span>{capability.label}</span>
              <strong>{capability.title}</strong>
              <p>{capability.copy}</p>
              <small>{capability.action} →</small>
            </a>
          ))}
        </div>
      </section>

      <footer className="productFooter">
        <div>
          <strong>Chakravyuh</strong>
          <span>Every rupee has a path.</span>
        </div>
        <p>Razorpay Test Mode environment · no live customer funds</p>
        <a href="/walkthrough">How the platform works →</a>
      </footer>
    </main>
  );
}
