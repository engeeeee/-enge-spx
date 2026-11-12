import type { NextConfig } from "next";

const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";
if (basePath && (!basePath.startsWith("/") || basePath.endsWith("/"))) {
    throw new Error(
        "NEXT_PUBLIC_BASE_PATH must start with / and have no trailing slash",
    );
}

const config: NextConfig = {
    output: "export",
    trailingSlash: true,
    basePath,
    images: { unoptimized: true },
    poweredByHeader: false,
    experimental: { cpus: 2 },
};

export default config;
