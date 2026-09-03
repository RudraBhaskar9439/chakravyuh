"use client";

import { useEffect, useState } from "react";

const introStorageKey = "chakravyuh:launch-sequence:v1";

export function LaunchSequence() {
  const [visible, setVisible] = useState(true);
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    const replayRequested = new URLSearchParams(window.location.search).get("intro") === "1";
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let alreadySeen = false;
    try {
      alreadySeen = window.sessionStorage.getItem(introStorageKey) === "seen";
    } catch {
      // A blocked storage API should not prevent the introduction from completing.
    }
    if (reducedMotion || (alreadySeen && !replayRequested)) {
      setVisible(false);
      return;
    }

    const exitTimer = window.setTimeout(() => setExiting(true), 3_150);
    const finishTimer = window.setTimeout(() => {
      rememberIntroduction();
      setVisible(false);
    }, 3_750);
    return () => {
      window.clearTimeout(exitTimer);
      window.clearTimeout(finishTimer);
    };
  }, []);

  function skip(): void {
    rememberIntroduction();
    setExiting(true);
    window.setTimeout(() => setVisible(false), 420);
  }

  if (!visible) return null;

  return (
    <section
      className={`launchSequence${exiting ? " isExiting" : ""}`}
      aria-label="Chakravyuh introduction"
    >
      <div className="launchGrid" aria-hidden="true" />
      <div className="launchTopline">
        <span>PAYMENT RECOVERY CONTROL PLANE</span>
        <button onClick={skip} type="button">
          Skip intro
        </button>
      </div>

      <div className="launchCanvas" aria-hidden="true">
        <svg viewBox="0 0 1200 560" role="presentation">
          <defs>
            <linearGradient id="launch-line" x1="0" x2="1">
              <stop offset="0" stopColor="#5d4523" />
              <stop offset="0.55" stopColor="#e6aa4c" />
              <stop offset="1" stopColor="#62d09b" />
            </linearGradient>
            <radialGradient id="launch-core">
              <stop offset="0" stopColor="#f7d796" />
              <stop offset="0.35" stopColor="#e6aa4c" />
              <stop offset="1" stopColor="#5d4523" />
            </radialGradient>
            <filter id="launch-glow" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="9" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <path className="launchPath launchPathA" d="M105 280 C260 280 302 118 470 162" />
          <path className="launchPath launchPathB" d="M105 280 C260 280 312 442 470 398" />
          <path className="launchPath launchPathC" d="M470 162 C610 198 640 245 726 280" />
          <path className="launchPath launchPathD" d="M470 398 C610 362 640 315 726 280" />
          <path className="launchPath launchPathE" d="M726 280 C860 280 914 280 1088 280" />
          <path className="launchPath launchPathF" d="M470 162 C566 280 578 280 470 398" />

          <g className="launchNode launchNodePayment">
            <circle className="launchNodeHalo" cx="105" cy="280" r="28" />
            <circle className="launchNodeCore" cx="105" cy="280" r="9" />
          </g>
          <g className="launchNode launchNodeEvidence">
            <circle className="launchNodeHalo" cx="470" cy="162" r="28" />
            <circle className="launchNodeCore" cx="470" cy="162" r="9" />
          </g>
          <g className="launchNode launchNodePolicy">
            <circle className="launchNodeHalo" cx="470" cy="398" r="28" />
            <circle className="launchNodeCore" cx="470" cy="398" r="9" />
          </g>
          <g className="launchNode launchNodeDecision">
            <circle className="launchNodeHalo" cx="726" cy="280" r="34" />
            <circle className="launchNodeCore" cx="726" cy="280" r="11" />
          </g>
          <g className="launchNode launchNodeProvider">
            <circle className="launchResolvedHalo" cx="1088" cy="280" r="32" />
            <circle className="launchResolvedCore" cx="1088" cy="280" r="10" />
          </g>
          <circle className="launchSignal" cx="0" cy="0" r="7" filter="url(#launch-glow)" />
        </svg>

        <div className="launchLabel launchLabelPayment">
          <span>01</span>
          <strong>PAYMENT</strong>
          <small>signal received</small>
        </div>
        <div className="launchLabel launchLabelEvidence">
          <span>02</span>
          <strong>EVIDENCE</strong>
          <small>journey linked</small>
        </div>
        <div className="launchLabel launchLabelPolicy">
          <span>03</span>
          <strong>POLICY</strong>
          <small>action bounded</small>
        </div>
        <div className="launchLabel launchLabelProvider">
          <span>04</span>
          <strong>CONFIRMED</strong>
          <small>provider verified</small>
        </div>
      </div>

      <div className="launchIdentity">
        <div className="launchMark">च</div>
        <div>
          <h1>Chakravyuh</h1>
          <p>Every rupee has a path.</p>
        </div>
      </div>

      <div className="launchFooter">
        <div className="launchProgress">
          <span />
        </div>
        <span>DETECT</span>
        <span>EXPLAIN</span>
        <span>GOVERN</span>
        <span>CONFIRM</span>
      </div>
    </section>
  );
}

function rememberIntroduction(): void {
  try {
    window.sessionStorage.setItem(introStorageKey, "seen");
  } catch {
    // Session storage is an enhancement; the sequence remains dismissible without it.
  }
}
