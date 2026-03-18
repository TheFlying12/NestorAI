"use client";

import { ArrowRight, Sparkles } from "lucide-react";
import Link from "next/link";
import { SignInButton, SignUpButton, Show } from "@clerk/nextjs";

export function Hero() {
  return (
    <section className="relative overflow-hidden pt-20 pb-24" style={{ background: "#FAF9F6" }}>
      {/* Decorative blobs */}
      <div
        className="absolute top-0 right-0 w-[500px] h-[500px] rounded-full pointer-events-none"
        style={{ background: "radial-gradient(circle, rgba(94,111,82,0.10) 0%, transparent 70%)" }}
      />
      <div
        className="absolute bottom-0 left-0 w-[400px] h-[400px] rounded-full pointer-events-none"
        style={{ background: "radial-gradient(circle, rgba(200,169,106,0.08) 0%, transparent 70%)" }}
      />

      <div className="relative max-w-6xl mx-auto px-5 text-center">
        {/* Eyebrow */}
        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-bold uppercase tracking-wide mb-6" style={{ background: "rgba(94,111,82,0.10)", color: "#5E6F52" }}>
          <Sparkles size={14} />
          Built for local-first intelligence
        </div>

        {/* Headline */}
        <h1
          className="font-display font-bold mb-6 mx-auto"
          style={{ fontSize: "clamp(2.2rem, 5vw, 3.6rem)", lineHeight: 1.15, maxWidth: "18ch", color: "#2B2B2B" }}
        >
          Your personal AI assistant, on your terms.
        </h1>

        {/* Subhead */}
        <p className="text-lg mb-10 mx-auto" style={{ maxWidth: "52ch", color: "#6B7C8F" }}>
          Nestor AI is a vertically integrated ecosystem for building reliable personal agents
          while keeping control over your data, workflows, and runtime.
        </p>

        {/* CTA row */}
        <div className="flex flex-wrap items-center justify-center gap-4">
          <Show when="signed-out">
            <SignUpButton forceRedirectUrl="/chat">
              <button className="inline-flex items-center gap-2 font-bold px-6 py-3 rounded-xl transition-colors text-base" style={{ background: "#5E6F52", color: "#FAF9F6" }}
                onMouseEnter={e => (e.currentTarget.style.background = "#4a5840")}
                onMouseLeave={e => (e.currentTarget.style.background = "#5E6F52")}
              >
                Get Started <ArrowRight size={18} />
              </button>
            </SignUpButton>
            <SignInButton forceRedirectUrl="/chat">
              <button className="inline-flex items-center gap-2 font-semibold px-6 py-3 rounded-xl transition-colors text-base" style={{ border: "1px solid #E8E4DC", color: "#2B2B2B", background: "transparent" }}
                onMouseEnter={e => (e.currentTarget.style.background = "#F1EFEA")}
                onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
              >
                Sign In
              </button>
            </SignInButton>
          </Show>
          <Show when="signed-in">
            <Link
              href="/chat"
              className="inline-flex items-center gap-2 font-bold px-6 py-3 rounded-xl transition-colors text-base"
              style={{ background: "#5E6F52", color: "#FAF9F6" }}
            >
              Open App <ArrowRight size={18} />
            </Link>
          </Show>
        </div>
      </div>
    </section>
  );
}
