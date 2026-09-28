import type { MetadataRoute } from "next";

/** The web app manifest: what a phone uses when VerifyGH is added to the home screen. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "VerifyGH",
    short_name: "VerifyGH",
    description: "Buy verification numbers with convenient Ghanaian payments.",
    start_url: "/dashboard",
    scope: "/",
    display: "standalone",
    background_color: "#F6F8F7",
    theme_color: "#0B6446",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      {
        src: "/icons/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
