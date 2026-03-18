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
    <section className="py-20 bg-gradient-to-b from-white to-[#f3f7f5]">
      <div className="max-w-6xl mx-auto px-5">
        <div className="text-center mb-14">
          <h2
            className="font-display font-bold text-gray-900 mb-3"
            style={{ fontSize: "clamp(1.6rem, 3vw, 2.3rem)" }}
          >
            How it works
          </h2>
          <p className="text-gray-500 text-base">
            From prototype to daily routine in three steps.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {steps.map(({ number, title, description }, i) => (
            <div key={title} className="relative flex flex-col items-center text-center">
              {/* Connector line */}
              {i < steps.length - 1 && (
                <div className="hidden md:block absolute top-6 left-[60%] w-[80%] h-px bg-primary/20" />
              )}

              <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mb-5 relative z-10">
                <span className="font-display font-bold text-primary text-sm">{number}</span>
              </div>
              <h3 className="font-display font-bold text-gray-900 mb-2 text-lg">{title}</h3>
              <p className="text-gray-500 text-sm leading-relaxed max-w-xs">{description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
