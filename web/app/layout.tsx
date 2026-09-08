import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Nav, RoleBar } from "@/components/Shell";
import { SessionProvider } from "@/lib/session";
import "./globals.css";

export const metadata: Metadata = {
  title: "SAMVEDNA",
  description:
    "Predictive personnel stress and welfare monitoring for uniformed forces. " +
    "The model raises the concern; deterministic arithmetic decides; a welfare " +
    "officer takes the action.",
  // Serves /manifest.webmanifest from app/manifest.ts, which is what makes the
  // personnel app installable on a phone.
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "SAMVEDNA",
    // The header is --brand-deep, so a translucent bar lets it run under the
    // status bar rather than sitting below a white strip.
    statusBarStyle: "black-translucent",
  },
  // Nothing here is for the public internet, and an indexed welfare system is
  // a reconnaissance gift. Search engines are told to stay out; the real
  // control is that it is hosted inside the force's own network.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  // Matches --brand-deep. Sets the phone's status bar and task-switcher colour.
  themeColor: "#16243D",
  width: "device-width",
  initialScale: 1,
  // Deliberately not locked. Pinch-zoom is how somebody reads a consent screen
  // in a script they find small, and disabling it to make an app feel native
  // takes that away from exactly the people who need it.
  maximumScale: 5,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SessionProvider>
          <header className="topbar">
            <div className="topbar-inner">
              <Link href="/" className="brand">
                <span className="name">SAMVEDNA</span>
                <span className="tag">Welfare support · never disciplinary</span>
              </Link>
              <Nav />
            </div>
          </header>
          <RoleBar />
          <main className="shell">{children}</main>
        </SessionProvider>
      </body>
    </html>
  );
}
