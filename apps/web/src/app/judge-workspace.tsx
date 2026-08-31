export function JudgeWorkspace() {
  return (
    <main className="workspaceShell">
      <section className="workspaceHero">
        <div>
          <p className="eyebrow">Razorpay Test Mode · verifiable recovery</p>
          <h1>Watch one broken payment repair itself.</h1>
          <p>
            Choose a real provider-backed Test Mode failure or authorization, follow its evidence
            graph through detection and controlled recovery, then independently verify the final
            state.
          </p>
          <div className="workspaceActions">
            <a className="workspacePrimary" href="/walkthrough">
              Start the judge walkthrough <span aria-hidden="true">→</span>
            </a>
            <a className="workspaceSecondary" href="/payments/authorize">
              Recover an uncaptured payment
            </a>
            <a className="workspaceSecondary" href="/payments/recover-failure">
              Recover a failed payment
            </a>
          </div>
        </div>
        <aside aria-label="Judge journey">
          <p>Judge journey</p>
          <ol>
            <li>
              <span>01</span>
              <div>
                <strong>Break</strong>
                <small>Fail ₹10 or deliberately leave an authorization uncaptured.</small>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>Understand</strong>
                <small>Inspect deterministic detection and the bounded AI diagnosis.</small>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <strong>Recover</strong>
                <small>Apply dual control and one exact policy-approved action.</small>
              </div>
            </li>
            <li>
              <span>04</span>
              <div>
                <strong>Challenge</strong>
                <small>Re-query Razorpay and verify every content hash.</small>
              </div>
            </li>
          </ol>
        </aside>
      </section>

      <section className="workspaceProofs" aria-label="Product evidence">
        <a href="/walkthrough">
          <span>Guided walkthrough</span>
          <strong>Understand the product in four minutes</strong>
          <p>One linear route through provider failure, graph evidence, recovery and proof.</p>
        </a>
        <a href="/payments/recover-failure">
          <span>Revenue recovery</span>
          <strong>Fail, diagnose and recover a payment</strong>
          <p>A real Test Mode failure becomes one expiring provider-hosted recovery path.</p>
        </a>
        <a href="/recoveries/verified">
          <span>Provider proof</span>
          <strong>Inspect a completed recovery</strong>
          <p>Original authorization, current Razorpay state, receipt and hash chain.</p>
        </a>
        <a href="/trace">
          <span>Money Trace</span>
          <strong>Resolve any known identifier</strong>
          <p>Payment, order, incident and content-addressed evidence lookup.</p>
        </a>
        <a href="/judge">
          <span>Scale evidence</span>
          <strong>Challenge the reliability claims</strong>
          <p>Sealed tournament, live-model, pipeline and chaos measurements.</p>
        </a>
      </section>

      <footer className="workspaceFooter">
        <p>No live funds move. Judge access uses server-scoped Test Mode credentials.</p>
        <a href="/operations">Secure operator console →</a>
      </footer>
    </main>
  );
}
