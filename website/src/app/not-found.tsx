import { asset } from "@/lib/content";
export default function NotFound() {
    return (
        <main className="not-found">
            <img
                src={asset("/brand/logo.svg")}
                width="64"
                height="64"
                alt="ENGE SPX"
            />
            <span className="eyebrow">404 / THIS SPACE IS EMPTY</span>
            <h1>这里还没有工作区。</h1>
            <p>你要找的页面可能已移动，回到首页继续。</p>
            <a className="button button-primary" href={asset("/")}>
                返回 ENGE SPX 首页
            </a>
        </main>
    );
}
