import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { AuthGuard } from "@/components/auth/AuthGuard";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains-mono",
});

export const metadata: Metadata = {
  title: "ZuiGO WebIQ",
  description: "Website intelligence platform",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="antialiased selection:bg-z-accent-subtle selection:text-z-ink bg-z-canvas text-z-ink">
        <AuthGuard>
          {children}
        </AuthGuard>
      </body>
    </html>
  );
}
