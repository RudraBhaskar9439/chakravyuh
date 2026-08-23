const architectureLayers = [
  {
    label: "Financial truth",
    value: "PostgreSQL",
    description: "Append-only events and replayable canonical state",
  },
  {
    label: "Relationship model",
    value: "Temporal graph",
    description: "A rebuildable projection of money journeys and evidence",
  },
  {
    label: "Action boundary",
    value: "Policy first",
    description: "AI proposes; deterministic controls authorize",
  },
];

export default function Home() {
  return (
    <main>
      <section className="hero" aria-labelledby="product-title">
        <p className="eyebrow">Phase 1 · Production foundation</p>
        <h1 id="product-title">Chakravyuh</h1>
        <p className="tagline">Every rupee has a path.</p>
        <p className="summary">
          A self-healing money graph that finds broken payment journeys, assembles verifiable
          evidence, and proposes bounded recovery.
        </p>
        <div className="status" role="status">
          <span className="statusDot" aria-hidden="true" />
          Foundation operational
        </div>
      </section>

      <section className="principles" aria-label="Architecture principles">
        {architectureLayers.map((layer) => (
          <article key={layer.label}>
            <p>{layer.label}</p>
            <h2>{layer.value}</h2>
            <span>{layer.description}</span>
          </article>
        ))}
      </section>
    </main>
  );
}
