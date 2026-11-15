import os from "node:os";
import type { NextConfig } from "next";

// The dev server only runs its JavaScript for localhost by default, so a phone opening
// http://<laptop-ip>:3000 got a dead page. Allow this laptop's own network addresses
// (whatever Wi-Fi or hotspot it's on when the server starts). Dev only; production is unaffected.
const lanAddresses = Object.values(os.networkInterfaces())
  .flat()
  .filter((a): a is os.NetworkInterfaceInfo => !!a && a.family === "IPv4" && !a.internal)
  .map((a) => a.address);

const nextConfig: NextConfig = {
  // `npm run dev:https` builds into its own folder, so it runs next to `npm run dev` (Next allows one dev server
  // per build folder). It serves the family app over https, which the check-in call's camera and mic need (#118).
  distDir: process.env.NEXT_DIST_DIR || ".next",
  allowedDevOrigins: lanAddresses,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
