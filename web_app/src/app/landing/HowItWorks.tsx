const steps = [
  {
    number: "01",
    title: "Create",
    description:
      "Build agents with a clear interface for goals, memory, and tools in one local environment.",
  },
  {
    number: "02",
    title: "Experiment",
    description:
      "Test prompts, automations, and multi-step behavior quickly with reproducible runs and feedback loops.",
  },
  {
    number: "03",
    title: "Run",
    description:
      "Deploy personal agents into your daily workflow with stable local runtime and full visibility into outcomes.",
  },
];

export function HowItWorks() {
  return (
    <section className="py-20" style={{ background: "#FAF9F6" }}>
      <div className="max-w-6xl mx-auto px-5">
        <div className="text-center mb-14">
          <h2
            className="font-display font-bold mb-3"
            style={{ fontSize: "clamp(1.6rem, 3vw, 2.3rem)", color: "#2B2B2B" }}
          >
            How it works
          </h2>
          <p className="text-base" style={{ color: "#6B7C8F" }}>
            From prototype to daily routine in three steps.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {steps.map(({ number, title, description }, i) => (
            <div key={title} className="relative flex flex-col items-center text-center">
              {i < steps.length - 1 && (
                <div className="hidden md:block absolute top-6 left-[60%] w-[80%] h-px" style={{ background: "rgba(94,111,82,0.20)" }} />
              )}
              <div className="w-12 h-12 rounded-full flex items-center justify-center mb-5 relative z-10" style={{ background: "rgba(94,111,82,0.12)" }}>
                <span className="font-display font-bold text-sm" style={{ color: "#5E6F52" }}>{number}</span>
              </div>
              <h3 className="font-display font-bold mb-2 text-lg" style={{ color: "#2B2B2B" }}>{title}</h3>
              <p className="text-sm leading-relaxed max-w-xs" style={{ color: "#6B7C8F" }}>{description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
