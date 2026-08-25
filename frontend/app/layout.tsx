import type { Metadata } from "next";
import { IBM_Plex_Sans } from "next/font/google";
import { AudioProvider } from "@/components/AudioProvider";
import MiniPlayer from "@/components/MiniPlayer";
import "./globals.css";

const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Backecast",
  description: "A small podcast platform.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="dark" className={`${plexSans.variable} h-full antialiased`}>
      <body className="min-h-full bg-bg text-text">
        <AudioProvider>
          <main>{children}</main>
          <MiniPlayer />
        </AudioProvider>
      </body>
    </html>
  );
}
