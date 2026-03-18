"use client";

import { ArrowRight, Sparkles } from "lucide-react";
import Link from "next/link";
import { SignInButton, SignUpButton, Show } from "@clerk/nextjs";

export function Hero() {
  return (
    <section className="relative overflow-hidden pt-20 pb-24 bg-gradient-to-br from-[#f3f7f5] via-white to-[#eaf6f1]">
      {/* Decorative blobs */}
      <div
        className="absolute top-0 right-0 w-[500px] h-[500px] rounded-full pointer-events-none"
        style={{
          background:
            "radial-gradient(circle, rgba(15,122,89,0.10) 0%, transparent 70%)",
        }}
      />
      <div
        className="absolute bottom-0 left-0 w-[400px] h-[400px] rounded-full pointer-events-none"
        style={{
          background:
            "radial-gradient(circle, rgba(68,179,140,0.12) 0%, transparent 70%)",
        }}
      />

      <div className="relative max-w-6xl mx-auto px-5 text-center">
        {/* Eyebrow */}
        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-primary/10 text-primary text-sm font-bold uppercase tracking-wide mb-6">
          <Sparkles size={14} />
          Built for local-first intelligence
        </div>

        {/* Headline */}
        <h1
          className="font-display font-bold text-gray-900 mb-6 mx-auto"
          style={{ fontSize: "clamp(2.2rem, 5vw, 3.6rem)", lineHeight: 1.15, maxWidth: "18ch" }}
        >
          Your personal AI assistant, on your terms.
        </h1>

        {/* Subhead */}
        <p className="text-gray-500 text-lg mb-10 mx-auto" style={{ maxWidth: "52ch" }}>
          Nestor AI is a vertically integrated ecosystem for building reliable personal agents
          while keeping control over your data, workflows, and runtime.
        </p>

        {/* CTA row */}
        <div className="flex flex-wrap items-center justify-center gap-4 mb-16">
          <Show when="signed-out">
            <SignUpButton forceRedirectUrl="/chat">
              <button className="inline-flex items-center gap-2 bg-primary hover:bg-primary-dark text-white font-bold px-6 py-3 rounded-xl transition-colors text-base shadow-lg shadow-primary/20">
                Get Started Free <ArrowRight size={18} />
              </button>
            </SignUpButton>
            <SignInButton forceRedirectUrl="/chat">
              <button className="inline-flex items-center gap-2 border border-gray-200 text-gray-700 font-semibold px-6 py-3 rounded-xl hover:bg-gray-50 transition-colors text-base">
                Sign In
              </button>
            </SignInButton>
          </Show>
          <Show when="signed-in">
            <Link
              href="/chat"
              className="inline-flex items-center gap-2 bg-primary hover:bg-primary-dark text-white font-bold px-6 py-3 rounded-xl transition-colors text-base shadow-lg shadow-primary/20"
            >
              Open App <ArrowRight size={18} />
            </Link>
          </Show>
        </div>

        {/* Feature highlights */}
        <div className="flex flex-wrap items-center justify-center gap-8 text-sm font-semibold text-gray-500">
          {["No credit card required", "Local-first by design", "Full data control"].map((f) => (
            <span key={f} className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-primary inline-block" />
              {f}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
