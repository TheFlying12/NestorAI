"use client";

export const dynamic = "force-dynamic";

import { Header } from "./landing/Header";
import { Hero } from "./landing/Hero";
import { Features } from "./landing/Features";
import { HowItWorks } from "./landing/HowItWorks";
import { Testimonials } from "./landing/Testimonials";
import { CTA } from "./landing/CTA";
import { Footer } from "./landing/Footer";

export default function LandingPage() {
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
        <Hero />
        <Features />
        <HowItWorks />
        <Testimonials />
        <CTA />
      </main>
      <Footer />
    </div>
  );
}
