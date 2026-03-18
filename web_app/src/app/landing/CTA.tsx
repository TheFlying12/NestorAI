"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { SignUpButton, Show } from "@clerk/nextjs";

export function CTA() {
  return (
    <section className="py-20 bg-gradient-to-br from-[#f3f7f5] to-[#eaf6f1]">
      <div className="max-w-3xl mx-auto px-5 text-center">
        <h2
          className="font-display font-bold text-gray-900 mb-4"
          style={{ fontSize: "clamp(1.7rem, 3.5vw, 2.6rem)" }}
        >
          Ready to build your personal AI?
        </h2>
        <p className="text-gray-500 text-base mb-8 mx-auto" style={{ maxWidth: "48ch" }}>
          Sign up and start running your own agents today. No credit card required.
        </p>

        <Show when="signed-out">
          <SignUpButton forceRedirectUrl="/chat">
            <button className="inline-flex items-center gap-2 bg-primary hover:bg-primary-dark text-white font-bold px-8 py-4 rounded-xl transition-colors text-base shadow-lg shadow-primary/25">
              Get Started Free <ArrowRight size={18} />
            </button>
          </SignUpButton>
        </Show>
        <Show when="signed-in">
          <Link
            href="/chat"
            className="inline-flex items-center gap-2 bg-primary hover:bg-primary-dark text-white font-bold px-8 py-4 rounded-xl transition-colors text-base shadow-lg shadow-primary/25"
          >
            Open App <ArrowRight size={18} />
          </Link>
        </Show>
      </div>
    </section>
  );
}
