export function JudgeWorkspace() {
  return (
    <main className="workspaceShell">
      <section className="workspaceHero">
        <div>
          <p className="eyebrow">Razorpay Test Mode · verifiable recovery</p>
          <h1>Watch one broken payment repair itself.</h1>
          <p>
            Create a real provider-backed Test Mode authorization, follow its evidence graph through
            detection and controlled recovery, then independently ask Razorpay for the final state.
          </p>
          <div className="workspaceActions">
            <a className="workspacePrimary" href="/payments/authorize">
              Start verified recovery <span aria-hidden="true">→</span>
            </a>
            <a href="/trace">Find an existing transaction</a>
          </div>
        </div>
        <aside aria-label="Judge journey">
          <p>Judge journey</p>
          <ol>
            <li>
              <span>01</span>
              <div>
                <strong>Break</strong>
                <small>Authorize ₹10 and deliberately leave it uncaptured.</small>
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
