/** Safe markdown → HTML for chat messages, with syntax highlighting. */
import { marked, type Tokens } from "marked";
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import go from "highlight.js/lib/languages/go";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import python from "highlight.js/lib/languages/python";
import rust from "highlight.js/lib/languages/rust";
import sql from "highlight.js/lib/languages/sql";
import swift from "highlight.js/lib/languages/swift";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import c from "highlight.js/lib/languages/c";
import cpp from "highlight.js/lib/languages/cpp";

for (const [name, lang] of Object.entries({
  bash, css, go, java, javascript, json, markdown, python, rust, sql, swift, typescript, xml, yaml, c, cpp,
})) hljs.registerLanguage(name, lang);
hljs.registerAliases(["sh", "shell", "zsh", "console"], { languageName: "bash" });
hljs.registerAliases(["js", "jsx", "mjs"], { languageName: "javascript" });
hljs.registerAliases(["ts", "tsx"], { languageName: "typescript" });
hljs.registerAliases(["py"], { languageName: "python" });
hljs.registerAliases(["html", "svelte", "vue"], { languageName: "xml" });
hljs.registerAliases(["yml"], { languageName: "yaml" });
hljs.registerAliases(["md"], { languageName: "markdown" });

export const esc = (s: string) =>
  s.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]!);

/** Only links that open a web page or a mail draft — never javascript:, data:, file:… */
const safeHref = (href: string) => /^(https?:|mailto:)/i.test(href.trim());

function highlight(code: string, lang: string, auto: boolean): string {
  try {
    if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
    if (auto && code.length < 20_000) return hljs.highlightAuto(code).value;
  } catch { /* fall through to plain text */ }
  return esc(code);
}

function renderer(streaming: boolean) {
  const r = new marked.Renderer();
  r.code = ({ text, lang }: Tokens.Code) => {
    const l = (lang || "").split(/\s/)[0].toLowerCase();
    return `<div class="code-block"><div class="code-head"><span>${esc(l || "code")}</span><button type="button" data-copy>Copy</button></div>`
      + `<pre><code class="hljs">${highlight(text, l, !streaming)}</code></pre></div>`;
  };
  r.link = ({ href, text }: Tokens.Link) =>
    safeHref(href) ? `<a href="${esc(href)}" target="_blank" rel="noreferrer noopener">${text}</a>` : text;
  // Remote images would load (and leak that the page was read) as soon as the reply renders: show a link instead
  r.image = ({ href, text }: Tokens.Image) =>
    safeHref(href) ? `<a href="${esc(href)}" target="_blank" rel="noreferrer noopener">🖼 ${esc(text || "image")}</a>` : esc(text || "");
  r.html = ({ text }: Tokens.HTML | Tokens.Tag) => esc(text);
  return r;
}

const live = renderer(true);
const done = renderer(false);

export function renderMarkdown(src: string, streaming = false): string {
  return marked.parse(src, { renderer: streaming ? live : done, async: false, gfm: true, breaks: false }) as string;
}
