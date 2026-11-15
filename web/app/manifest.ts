import type { MetadataRoute } from "next";

// The family app installs to the home screen as "Miguel". The laptop dashboard at / isn't part of it.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Miguel",
    short_name: "Miguel",
    description: "See how Mom's day is going, send her things through Miguel, and check in.",
    start_url: "/family",
    scope: "/family",
    display: "standalone",
    orientation: "portrait",
    background_color: "#f7f2e8",
    theme_color: "#f7f2e8",
    icons: [
      { src: "/family/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/family/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/family/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
