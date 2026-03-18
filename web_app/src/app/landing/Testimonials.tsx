import { Star } from "lucide-react";

const testimonials = [
  {
    name: "Sarah K.",
    role: "Product Manager",
    avatar: "SK",
    quote:
      "Nestor's Budget Assistant changed how I think about my finances. It actually remembers our past conversations and builds on them.",
  },
  {
    name: "James R.",
    role: "Software Engineer",
    avatar: "JR",
    quote:
      "The local-first approach is exactly what I was looking for. My data doesn't leave my control, and the skill architecture is clean.",
  },
  {
    name: "Priya M.",
    role: "Startup Founder",
    avatar: "PM",
    quote:
      "We use Nestor internally to track hiring and habits. The multi-skill switching with persistent memory is genuinely useful.",
  },
];

export function Testimonials() {
  return (
    <section className="py-20" style={{ background: "#F1EFEA" }}>
      <div className="max-w-6xl mx-auto px-5">
        <div className="text-center mb-14">
          <h2
            className="font-display font-bold mb-3"
            style={{ fontSize: "clamp(1.6rem, 3vw, 2.3rem)", color: "#2B2B2B" }}
          >
            People who use it, love it
          </h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {testimonials.map(({ name, role, avatar, quote }) => (
            <article
              key={name}
              className="p-6 rounded-2xl border flex flex-col gap-4"
              style={{ background: "#FAF9F6", borderColor: "#E8E4DC" }}
            >
              {/* Stars — soft gold */}
              <div className="flex gap-1">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Star key={i} size={14} style={{ fill: "#C8A96A", color: "#C8A96A" }} />
                ))}
              </div>

              <p className="text-sm leading-relaxed flex-1" style={{ color: "#6B7C8F" }}>&ldquo;{quote}&rdquo;</p>

              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full flex items-center justify-center font-bold text-xs flex-shrink-0" style={{ background: "rgba(94,111,82,0.15)", color: "#5E6F52" }}>
                  {avatar}
                </div>
                <div>
                  <p className="text-sm font-bold" style={{ color: "#2B2B2B" }}>{name}</p>
                  <p className="text-xs" style={{ color: "#6B7C8F" }}>{role}</p>
                </div>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
