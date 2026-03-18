import Link from "next/link";

export function Footer() {
  return (
    <footer className="border-t border-gray-100 bg-white">
      <div className="max-w-6xl mx-auto px-5 py-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="font-display font-bold text-gray-900 text-base mb-1">Nestor AI</p>
          <p className="text-gray-400 text-sm">
            &copy; {new Date().getFullYear()} Nestor AI. All rights reserved.
          </p>
        </div>

        <nav className="flex items-center gap-6">
          <Link href="/" className="text-sm text-gray-500 hover:text-gray-800 transition-colors">
            Home
          </Link>
          <Link href="/about" className="text-sm text-gray-500 hover:text-gray-800 transition-colors">
            About Us
          </Link>
        </nav>
      </div>
    </footer>
  );
}
