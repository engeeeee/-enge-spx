import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
export function SectionLabel({
    number,
    children,
}: {
    number: string;
    children: ReactNode;
}) {
    return (
        <div className="section-label">
            <span className="mono">{number}</span>
            <span className="label-line" />
            <span>{children}</span>
        </div>
    );
}
export function TextLink({
    href,
    children,
}: {
    href: string;
    children: ReactNode;
}) {
    return (
        <a className="text-link" href={href} target="_blank" rel="noreferrer">
            {children}
            <ArrowUpRight size={15} />
        </a>
    );
}
