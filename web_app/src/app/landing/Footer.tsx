import Link from "next/link";

export function Footer() {
  return (
    <footer style={{ background: "#2B2B2B" }}>
      <div className="max-w-6xl mx-auto px-5 py-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="font-display font-bold text-base mb-1" style={{ color: "#FAF9F6" }}>Nestor AI</p>
          <p className="text-sm" style={{ color: "#9A9A9A" }}>
            &copy; {new Date().getFullYear()} Nestor AI. All rights reserved.
          </p>
        </div>

        <nav className="flex items-center gap-6">
          <Link href="/" className="text-sm transition-colors" style={{ color: "#9A9A9A" }}>
            Home
          </Link>
          <Link href="/about" className="text-sm transition-colors" style={{ color: "#9A9A9A" }}>
            About Us
          </Link>
        </nav>
      </div>
    </footer>
  );
}
