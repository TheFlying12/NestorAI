"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { SignUpButton, Show } from "@clerk/nextjs";

export function CTA() {
  return (
    <section className="py-20" style={{ background: "#FAF9F6" }}>
      <div className="max-w-3xl mx-auto px-5 text-center">
        <h2
          className="font-display font-bold mb-4"
          style={{ fontSize: "clamp(1.7rem, 3.5vw, 2.6rem)", color: "#2B2B2B" }}
        >
          Ready to build your personal AI?
        </h2>
        <p className="text-base mb-8 mx-auto" style={{ maxWidth: "48ch", color: "#6B7C8F" }}>
          Sign up and start running your own agents today.
        </p>

        <Show when="signed-out">
          <SignUpButton forceRedirectUrl="/chat">
            <button
              className="inline-flex items-center gap-2 font-bold px-8 py-4 rounded-xl transition-colors text-base"
              style={{ background: "#5E6F52", color: "#FAF9F6" }}
              onMouseEnter={e => (e.currentTarget.style.background = "#4a5840")}
              onMouseLeave={e => (e.currentTarget.style.background = "#5E6F52")}
            >
              Get Started <ArrowRight size={18} />
            </button>
          </SignUpButton>
        </Show>
        <Show when="signed-in">
          <Link
            href="/chat"
            className="inline-flex items-center gap-2 font-bold px-8 py-4 rounded-xl transition-colors text-base"
            style={{ background: "#5E6F52", color: "#FAF9F6" }}
          >
            Open App <ArrowRight size={18} />
          </Link>
        </Show>
      </div>
    </section>
  );
}
