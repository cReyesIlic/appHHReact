import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function withoutFrontmatter(content) {
  return String(content || "")
    .replace(/^\uFEFF/, "")
    .replace(/^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/, "");
}

export function MarkdownView({ content = "", className = "", stripFrontmatter = false }) {
  const markdown = stripFrontmatter ? withoutFrontmatter(content) : String(content || "");

  return (
    <div className={`markdown-view${className ? ` ${className}` : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node: _node, href, ...props }) => {
            const externalProps = href?.startsWith("#")
              ? {}
              : { target: "_blank", rel: "noreferrer noopener" };
            return <a href={href} {...externalProps} {...props} />;
          },
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
