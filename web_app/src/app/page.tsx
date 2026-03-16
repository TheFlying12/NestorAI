"use client";

import { useState } from "react";
import Link from "next/link";
import { SignInButton, SignUpButton, Show } from "@clerk/nextjs";
import styles from "./landing.module.css";

export default function LandingPage() {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className={styles.page}>
      <header className={styles.siteHeader}>
        <div className={`${styles.container} ${styles.navWrap}`}>
          <Link href="/" className={styles.logo}>Nestor AI</Link>
          <button
            className={styles.navToggle}
            aria-label="Toggle navigation"
            aria-expanded={navOpen}
            onClick={() => setNavOpen(!navOpen)}
          >
            Menu
          </button>
          <nav className={`${styles.siteNav} ${navOpen ? styles.open : ""}`}>
            <Link href="/" className={styles.active}>Home</Link>
            <Link href="/about">About Us</Link>
            <Show when="signed-in">
              <Link href="/chat" className={`${styles.btn} ${styles.btnSmall}`}>Go to App</Link>
            </Show>
            <Show when="signed-out">
              <SignInButton forceRedirectUrl="/chat">
                <button className={`${styles.btn} ${styles.btnSmall}`}>Sign In</button>
              </SignInButton>
            </Show>
          </nav>
        </div>
      </header>

      <main>
        <section className={styles.hero}>
          <div className={`${styles.container} ${styles.heroGrid}`}>
            <div>
              <p className={styles.eyebrow}>Built for local-first intelligence</p>
              <h1>Create, test, and run personal AI agents on your own machine.</h1>
              <p className={styles.lead}>
                Nestor AI is a vertically integrated ecosystem for building reliable personal agents
                while keeping control over your data, workflows, and runtime.
              </p>
              <div className={styles.heroActions}>
                <Show when="signed-out">
                  <SignUpButton forceRedirectUrl="/chat">
                    <button className={styles.btn}>Get Started</button>
                  </SignUpButton>
                  <SignInButton forceRedirectUrl="/chat">
                    <button className={`${styles.btn} ${styles.btnGhost}`}>Sign In</button>
                  </SignInButton>
                </Show>
                <Show when="signed-in">
                  <Link href="/chat" className={styles.btn}>Go to App</Link>
                </Show>
              </div>
            </div>
            <aside className={styles.heroCard}>
              <h2>Why Nestor AI</h2>
              <ul>
                <li>Unified tooling for agent creation, iteration, and deployment</li>
                <li>Local execution with transparent control over agent behavior</li>
                <li>Fast experimentation loop from prototype to production routine</li>
                <li>Composable architecture for personal and team workflows</li>
              </ul>
            </aside>
          </div>
        </section>

        <section className={styles.section}>
          <div className={styles.container}>
            <h2>How It Works</h2>
            <div className={`${styles.cards} ${styles.threeCol}`}>
              <article className={styles.card}>
                <h3>1. Create</h3>
                <p>Build agents with a clear interface for goals, memory, and tools in one local environment.</p>
              </article>
              <article className={styles.card}>
                <h3>2. Experiment</h3>
                <p>Test prompts, automations, and multi-step behavior quickly with reproducible runs and feedback loops.</p>
              </article>
              <article className={styles.card}>
                <h3>3. Run</h3>
                <p>Deploy personal agents into your daily workflow with stable local runtime and visibility into outcomes.</p>
              </article>
            </div>
          </div>
        </section>

        <section className={`${styles.section} ${styles.ctaBand}`}>
          <div className={styles.container}>
            <div className={styles.ctaRow}>
              <div>
                <h2>Ready to get started?</h2>
                <p>Sign up and start building your personal AI assistant today.</p>
              </div>
              <Show when="signed-out">
                <SignUpButton forceRedirectUrl="/chat">
                  <button className={styles.btn}>Get Started Free</button>
                </SignUpButton>
              </Show>
              <Show when="signed-in">
                <Link href="/chat" className={styles.btn}>Go to App</Link>
              </Show>
            </div>
          </div>
        </section>
      </main>

      <footer className={styles.siteFooter}>
        <div className={`${styles.container} ${styles.footerWrap}`}>
          <p>&copy; {new Date().getFullYear()} Nestor AI. All rights reserved.</p>
          <div>
            <Link href="/about">About Us</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
