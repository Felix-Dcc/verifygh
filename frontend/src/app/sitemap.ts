import type { MetadataRoute } from "next";

import { APP_PAGES } from "@/lib/app-pages";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_ORIGIN || "https://www.getverifygh.com";

/**
 * The public pages a search engine should know about, served as /sitemap.xml.
 * Signed-in screens (dashboard, wallet, orders, admin) are not listed: they
 * show nothing to a crawler but the sign-in page.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const pages: Array<[path: string, priority: number, changeFrequency: "daily" | "weekly" | "monthly"]> = [
    ["/", 1, "weekly"],
    ["/services", 0.9, "daily"],
    ["/help", 0.7, "monthly"],
    ["/rent-us-number", 0.8, "weekly"],
    ...APP_PAGES.map((page): [string, number, "weekly"] => [`/us-number/${page.slug}`, 0.8, "weekly"]),
    ["/register", 0.6, "monthly"],
    ["/terms", 0.3, "monthly"],
    ["/acceptable-use", 0.3, "monthly"],
    ["/privacy", 0.3, "monthly"],
  ];
  return pages.map(([path, priority, changeFrequency]) => ({
    url: `${SITE_URL}${path}`,
    changeFrequency,
    priority,
  }));
}
