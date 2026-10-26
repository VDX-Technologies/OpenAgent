import { Onboarding } from "@/components/Onboarding";
import type { Metadata } from "next";
import { Archivo, IBM_Plex_Mono } from "next/font/google";
import { Suspense } from "react";
import { Sidebar } from "@/components/Sidebar";
import "./globals.css";

const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-archivo",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--font-plex-mono",
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "VDX OpenAgent",
  description: "Local macOS AI agent — Ollama, Calendar, Reminders, Gmail, Discord",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${archivo.variable} ${mono.variable}`}>
      <body className="antialiased">
        <div className="app-shell flex h-screen overflow-hidden">
          <Suspense fallback={null}>
            <Sidebar />
          </Suspense>
          <main className="relative z-10 flex min-w-0 flex-1 flex-col">{children}</main>
        </div>
        <Onboarding />
      </body>
    </html>
  );
}
