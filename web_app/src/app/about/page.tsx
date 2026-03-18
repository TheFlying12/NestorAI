"use client";

export const dynamic = "force-dynamic";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { SignUpButton, Show } from "@clerk/nextjs";
import { Header } from "../landing/Header";
import { Footer } from "../landing/Footer";

export default function AboutPage() {
  return (
    <div
      style={{
        background: "#FAF9F6",
        color: "#2B2B2B",
        fontFamily: "'Manrope', -apple-system, BlinkMacSystemFont, sans-serif",
        lineHeight: 1.55,
        minHeight: "100vh",
      }}
    >
      <Header />

      <main>
        {/* Hero */}
        <section className="pt-20 pb-16" style={{ background: "#FAF9F6" }}>
          <div className="max-w-6xl mx-auto px-5">
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full text-sm font-bold uppercase tracking-wide mb-6" style={{ background: "rgba(94,111,82,0.10)", color: "#5E6F52" }}>
              About Nestor AI
            </div>
            <h1
              className="font-display font-bold mb-4"
              style={{ fontSize: "clamp(2rem, 4vw, 3rem)", lineHeight: 1.15, maxWidth: "22ch", color: "#2B2B2B" }}
            >
              Building practical local AI infrastructure for personal agents.
            </h1>
            <p className="text-lg" style={{ maxWidth: "52ch", color: "#6B7C8F" }}>
              Our mission is to make personal AI agents reliable, customizable, and fully
              controllable by the people who use them.
            </p>
          </div>
        </section>

        {/* Founders */}
        <section className="py-20" style={{ background: "#F1EFEA" }}>
          <div className="max-w-6xl mx-auto px-5">
            <h2
              className="font-display font-bold mb-10"
              style={{ fontSize: "clamp(1.6rem, 3vw, 2.3rem)", color: "#2B2B2B" }}
            >
              Founders
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {[
                { name: "Tejus Janakiraman", initials: "TJ" },
                { name: "Avi Mehta", initials: "AM" },
              ].map(({ name, initials }) => (
                <article
                  key={name}
                  className="p-6 rounded-2xl border flex items-center gap-4"
                  style={{ background: "#FAF9F6", borderColor: "#E8E4DC" }}
                >
                  <div className="w-12 h-12 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0" style={{ background: "rgba(94,111,82,0.15)", color: "#5E6F52" }}>
                    {initials}
                  </div>
                  <div>
                    <h3 className="font-display font-bold text-base" style={{ color: "#2B2B2B" }}>{name}</h3>
                    <p className="text-sm font-semibold" style={{ color: "#5E6F52" }}>Co-Founder</p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="py-20" style={{ background: "#FAF9F6" }}>
          <div className="max-w-3xl mx-auto px-5 text-center">
            <h2
              className="font-display font-bold mb-4"
              style={{ fontSize: "clamp(1.7rem, 3.5vw, 2.6rem)", color: "#2B2B2B" }}
            >
              Interested in collaborating with us?
            </h2>
            <p className="text-base mb-8" style={{ color: "#6B7C8F" }}>
              Schedule a demo and we can walk through the platform together.
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
                Go to App <ArrowRight size={18} />
              </Link>
            </Show>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}
