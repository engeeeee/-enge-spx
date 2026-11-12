import type { MetadataRoute } from "next";
import { product } from "@/lib/content";
export const dynamic = "force-static";
export default function sitemap(): MetadataRoute.Sitemap {
    return [
        {
            url: product.site,
            lastModified: "2026-11-12",
            changeFrequency: "monthly",
            priority: 1,
        },
    ];
}
