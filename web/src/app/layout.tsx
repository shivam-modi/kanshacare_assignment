import './globals.css';
import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Kansha Care — Earthquake Telemetry',
  description: 'Real-time USGS earthquake feed, monitoring, and alerting.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="border-b border-[--border] bg-[--surface]">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
            <Link href="/" className="text-lg font-semibold tracking-tight">
              Kansha<span className="text-sev-elevated"> Care</span>
              <span className="ml-2 text-xs font-normal text-slate-400">earthquake telemetry</span>
            </Link>
            <nav className="flex items-center gap-6 text-sm">
              <Link href="/" className="hover:text-white">Global</Link>
              <Link href="/locations" className="hover:text-white">Locations</Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
