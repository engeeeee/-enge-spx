import type { MetadataRoute } from "next";
import { product } from "@/lib/content";
export const dynamic = "force-static";
export default function robots(): MetadataRoute.Robots {
    return {
        rules: {
            userAgent: "*",
            allow: "/",
            disallow: ["/previews/", "/deliverables/"],
        },
        sitemap: `${product.site}/sitemap.xml`,
    };
}
