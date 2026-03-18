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
        background: "#ffffff",
        color: "#152019",
        fontFamily: "'Manrope', -apple-system, BlinkMacSystemFont, sans-serif",
        lineHeight: 1.55,
        minHeight: "100vh",
      }}
    >
      <Header />

      <main>
        {/* Hero */}
        <section className="pt-20 pb-16 bg-gradient-to-br from-[#f3f7f5] via-white to-[#eaf6f1]">
          <div className="max-w-6xl mx-auto px-5">
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-primary/10 text-primary text-sm font-bold uppercase tracking-wide mb-6">
              About Nestor AI
            </div>
            <h1
              className="font-display font-bold text-gray-900 mb-4"
              style={{ fontSize: "clamp(2rem, 4vw, 3rem)", lineHeight: 1.15, maxWidth: "22ch" }}
            >
              Building practical local AI infrastructure for personal agents.
            </h1>
            <p className="text-gray-500 text-lg" style={{ maxWidth: "52ch" }}>
              Our mission is to make personal AI agents reliable, customizable, and fully
              controllable by the people who use them.
            </p>
          </div>
        </section>

        {/* Founders */}
        <section className="py-20 bg-white">
          <div className="max-w-6xl mx-auto px-5">
            <h2
              className="font-display font-bold text-gray-900 mb-10"
              style={{ fontSize: "clamp(1.6rem, 3vw, 2.3rem)" }}
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
                  className="p-6 rounded-2xl border border-gray-100 shadow-sm bg-[#fafafa] flex items-center gap-4"
                >
                  <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center text-primary font-bold text-sm flex-shrink-0">
                    {initials}
                  </div>
                  <div>
                    <h3 className="font-display font-bold text-gray-900 text-base">{name}</h3>
                    <p className="text-sm font-semibold text-primary">Co-Founder</p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="py-20 bg-gradient-to-br from-[#f3f7f5] to-[#eaf6f1]">
          <div className="max-w-3xl mx-auto px-5 text-center">
            <h2
              className="font-display font-bold text-gray-900 mb-4"
              style={{ fontSize: "clamp(1.7rem, 3.5vw, 2.6rem)" }}
            >
              Interested in collaborating with us?
            </h2>
            <p className="text-gray-500 text-base mb-8">
              Schedule a demo and we can walk through the platform together.
            </p>
            <Show when="signed-out">
              <SignUpButton forceRedirectUrl="/chat">
                <button className="inline-flex items-center gap-2 bg-primary hover:bg-primary-dark text-white font-bold px-8 py-4 rounded-xl transition-colors text-base shadow-lg shadow-primary/25">
                  Get Started <ArrowRight size={18} />
                </button>
              </SignUpButton>
            </Show>
            <Show when="signed-in">
              <Link
                href="/chat"
                className="inline-flex items-center gap-2 bg-primary hover:bg-primary-dark text-white font-bold px-8 py-4 rounded-xl transition-colors text-base shadow-lg shadow-primary/25"
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
