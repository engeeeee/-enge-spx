import { Navigation } from "@/components/interactions";
import { docs, product } from "@/lib/content";
import { HeroSection } from "@/components/sections/hero";
import { FeaturesSection } from "@/components/sections/features";
import { NetworkSection } from "@/components/sections/network";
import { WorkspaceSection } from "@/components/sections/workspace";
import { ResourcesSection } from "@/components/sections/resources";
import { SecuritySection } from "@/components/sections/security";
import { GetStartedSection } from "@/components/sections/get-started";
import { FaqSection } from "@/components/sections/faq";
import { Footer } from "@/components/sections/footer";

export default function Home() {
    const structuredData = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        name: product.name,
        applicationCategory: "DeveloperApplication",
        operatingSystem: "Windows x64",
        softwareVersion: product.version,
        url: product.site,
        downloadUrl: product.installer,
        license: docs.license,
        description:
            "Windows AI 编程隔离工作台，为 Claude Code、Codex 与 Chromium 提供容器工作区、身份隔离和可核对的代理路径。",
    };
    return (
        <>
            <script
                type="application/ld+json"
                dangerouslySetInnerHTML={{
                    __html: JSON.stringify(structuredData).replace(
                        /</g,
                        "\\u003c",
                    ),
                }}
            />
            <Navigation />
            <main id="main">
                <HeroSection />
                <FeaturesSection />
                <NetworkSection />
                <WorkspaceSection />
                <ResourcesSection />
                <SecuritySection />
                <GetStartedSection />
                <FaqSection />
            </main>
            <Footer />
        </>
    );
}
