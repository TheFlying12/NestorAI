"use client";

import { useState } from "react";
import Link from "next/link";
import { Menu, X } from "lucide-react";
import { SignInButton, SignUpButton, Show } from "@clerk/nextjs";

export function Header() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 backdrop-blur-md border-b border-[#E8E4DC]" style={{ background: "rgba(250,249,246,0.92)" }}>
      <div className="max-w-6xl mx-auto px-5 py-4 flex items-center justify-between gap-4">
        {/* Logo */}
        <Link href="/" className="font-display font-bold text-xl text-charcoal">
          Nestor AI
        </Link>

        {/* Desktop nav */}
        <nav className="hidden md:flex items-center gap-6">
          <Link href="/" className="text-sm font-semibold text-[#2B2B2B] hover:text-primary transition-colors">
            Home
          </Link>
          <Link href="/about" className="text-sm font-semibold text-[#2B2B2B] hover:text-primary transition-colors">
            About
          </Link>
          <Show when="signed-in">
            <Link
              href="/chat"
              className="text-sm font-semibold bg-primary text-warm px-4 py-2 rounded-lg hover:bg-primary-dark transition-colors"
            >
              Go to App
            </Link>
          </Show>
          <Show when="signed-out">
            <SignInButton forceRedirectUrl="/chat">
              <button className="text-sm font-semibold text-[#2B2B2B] hover:text-primary transition-colors">
                Sign In
              </button>
            </SignInButton>
            <SignUpButton forceRedirectUrl="/chat">
              <button className="text-sm font-semibold bg-primary text-warm px-4 py-2 rounded-lg hover:bg-primary-dark transition-colors">
                Get Started
              </button>
            </SignUpButton>
          </Show>
        </nav>

        {/* Mobile toggle */}
        <button
          className="md:hidden p-2 text-[#2B2B2B]"
          aria-label="Toggle menu"
          onClick={() => setOpen(!open)}
        >
          {open ? <X size={22} /> : <Menu size={22} />}
        </button>
      </div>

      {/* Mobile menu */}
      {open && (
        <div className="md:hidden border-t border-[#E8E4DC] bg-warm px-5 py-4 flex flex-col gap-4">
          <Link href="/" className="text-sm font-semibold text-[#2B2B2B]" onClick={() => setOpen(false)}>
            Home
          </Link>
          <Link href="/about" className="text-sm font-semibold text-[#2B2B2B]" onClick={() => setOpen(false)}>
            About
          </Link>
          <Show when="signed-in">
            <Link href="/chat" className="text-sm font-semibold text-primary" onClick={() => setOpen(false)}>
              Go to App →
            </Link>
          </Show>
          <Show when="signed-out">
            <SignInButton forceRedirectUrl="/chat">
              <button className="text-sm font-semibold text-[#2B2B2B] text-left">Sign In</button>
            </SignInButton>
            <SignUpButton forceRedirectUrl="/chat">
              <button className="text-sm font-semibold text-primary text-left">Get Started →</button>
            </SignUpButton>
          </Show>
        </div>
      )}
    </header>
  );
}
