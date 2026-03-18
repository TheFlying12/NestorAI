import { Zap, Shield, Users, BarChart3, Clock, CheckCircle2 } from "lucide-react";

const features = [
  {
    icon: Zap,
    title: "Instant Skill Switching",
    description:
      "Seamlessly switch between your Budget Assistant, Job Tracker, Habit Tracker, and more without losing context.",
  },
  {
    icon: Shield,
    title: "Your Data Stays Yours",
    description:
      "All agent logic runs with your own API keys. No vendor lock-in, no data harvesting, no black boxes.",
  },
  {
    icon: Users,
    title: "Multi-Skill Architecture",
    description:
      "Each skill is an independent Python module — composable, testable, and easy to extend with custom behavior.",
  },
  {
    icon: BarChart3,
    title: "Conversation Memory",
    description:
      "Nestor summarizes past conversations so your agent stays aware of context across long sessions and days.",
  },
  {
    icon: Clock,
    title: "Always Ready",
    description:
      "PWA-ready with real-time WebSocket streaming. Open it on mobile, desktop, or anywhere — no install required.",
  },
  {
    icon: CheckCircle2,
    title: "Production Hardened",
    description:
      "Built with retries, exponential backoff, graceful reconnect, and auth at every layer from day one.",
  },
];

export function Features() {
  return (
    <section className="py-20 bg-white">
      <div className="max-w-6xl mx-auto px-5">
        <div className="text-center mb-14">
          <h2
            className="font-display font-bold text-gray-900 mb-3"
            style={{ fontSize: "clamp(1.6rem, 3vw, 2.3rem)" }}
          >
            Everything you need, nothing you don&apos;t
          </h2>
          <p className="text-gray-500 text-base mx-auto" style={{ maxWidth: "50ch" }}>
            Nestor is built for reliability and transparency — not for demos.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {features.map(({ icon: Icon, title, description }) => (
            <article
              key={title}
              className="p-6 rounded-2xl border border-gray-100 hover:border-primary/20 hover:shadow-md transition-all bg-[#fafafa]"
            >
              <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center mb-4">
                <Icon size={20} className="text-primary" />
              </div>
              <h3 className="font-display font-bold text-gray-900 mb-2 text-base">{title}</h3>
              <p className="text-gray-500 text-sm leading-relaxed">{description}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
