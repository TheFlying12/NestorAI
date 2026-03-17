"use client";

import { useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { SignInButton, Show } from "@clerk/nextjs";
import styles from "../landing.module.css";

export default function AboutPage() {
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
            <Link href="/">Home</Link>
            <Link href="/about" className={styles.active}>About Us</Link>
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
        <section className={`${styles.hero} ${styles.subHero}`}>
          <div className={styles.container}>
            <p className={styles.eyebrow}>About Nestor AI</p>
            <h1>Building practical local AI infrastructure for personal agents.</h1>
            <p className={styles.lead}>
              Our mission is to make personal AI agents reliable, customizable, and fully controllable by the people who use them.
            </p>
          </div>
        </section>

        <section className={styles.section}>
          <div className={styles.container}>
            <h2>Founders</h2>
            <div className={`${styles.cards} ${styles.twoCol}`}>
              <article className={styles.card}>
                <Image
                  className={styles.founderPhoto}
                  src="/assets/TejusJ.jpg"
                  alt="Tejus Janakiraman"
                  width={96}
                  height={96}
                />
                <h3>Tejus Janakiraman</h3>
                <p className={styles.role}>Co-Founder</p>
                <p>Hi, I like to build stuff that makes my life easier. Who knew others would want that too?</p>
              </article>
              <article className={styles.card}>
                <Image
                  className={styles.founderPhoto}
                  src="/assets/AviMehta.png"
                  alt="Avi Mehta"
                  width={96}
                  height={96}
                />
                <h3>Avi Mehta</h3>
                <p className={styles.role}>Co-Founder</p>
                <p>Aside from building, I enjoy soccer, tennis, EDM, F1, swimming, and advocating for better urban design policies. I&apos;m also big on languages (I speak five!)</p>
              </article>
            </div>
          </div>
        </section>

        <section className={`${styles.section} ${styles.ctaBand}`}>
          <div className={styles.container}>
            <div className={styles.ctaRow}>
              <div>
                <h2>Interested in collaborating with us?</h2>
                <p>Schedule a demo and we can walk through the platform together.</p>
              </div>
              <Show when="signed-out">
                <SignInButton forceRedirectUrl="/chat">
                  <button className={styles.btn}>Get Started</button>
                </SignInButton>
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
            <Link href="/">Home</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
