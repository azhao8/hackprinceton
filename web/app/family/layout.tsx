import type { Metadata, Viewport } from "next";
import { DM_Mono, Figtree, Literata } from "next/font/google";
import { AlertLayer } from "@/components/family/AlertLayer";
import { DemoPanel } from "@/components/family/DemoPanel";
import { FamilyProvider } from "@/lib/family/store";
import "./family.css";

// Headings: Literata, a warm book serif with optical sizes (and plain, friendly f's).
const serif = Literata({
  subsets: ["latin"],
  axes: ["opsz"],
  style: ["normal", "italic"],
  variable: "--font-serif-display",
});
const figtree = Figtree({ subsets: ["latin"], variable: "--font-figtree" });
const dmMono = DM_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-dm-mono" });

export const metadata: Metadata = {
  title: "Miguel",
  description: "See how Mom's day is going, send her things through Miguel, and check in.",
  appleWebApp: { capable: true, title: "Miguel", statusBarStyle: "default" },
  icons: {
    icon: [{ url: "/family/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
    apple: [{ url: "/family/icons/icon-180.png", sizes: "180x180" }],
  },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: "#f7f2e8",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
};

export default function FamilyLayout({ children }: LayoutProps<"/family">) {
  return (
    <div className={`family-root flex-1 ${serif.variable} ${figtree.variable} ${dmMono.variable}`}>
      <FamilyProvider>
        {children}
        <AlertLayer />
        <DemoPanel />
      </FamilyProvider>
    </div>
  );
}
