import { useEffect, useId, useState } from "react";

type MermaidDiagramProps = {
  chart: string;
  className?: string;
};

/** LangGraph draw_mermaid embeds HTML like `<p>label</p>` which breaks rendering. */
export function sanitizeMermaid(chart: string): string {
  return chart
    .replace(/<\/?p>/gi, "")
    .replace(/&lt;p&gt;/gi, "")
    .replace(/&lt;\/p&gt;/gi, "")
    .trim();
}

let mermaidReady = false;

async function loadMermaid() {
  const mermaid = (await import("mermaid")).default;
  if (!mermaidReady) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "loose",
      theme: "neutral",
      flowchart: { curve: "basis", htmlLabels: false },
    });
    mermaidReady = true;
  }
  return mermaid;
}

function MermaidDiagram({ chart, className }: MermaidDiagramProps) {
  const reactId = useId().replace(/:/g, "");
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const cleaned = sanitizeMermaid(chart);

  useEffect(() => {
    let cancelled = false;
    if (!cleaned) {
      setSvg("");
      setError(null);
      return;
    }

    const renderId = `mermaid-${reactId}-${Math.abs(hashString(cleaned))}`;
    loadMermaid()
      .then((mermaid) => mermaid.render(renderId, cleaned))
      .then(({ svg: rendered }) => {
        if (!cancelled) {
          setSvg(rendered);
          setError(null);
        }
      })
      .catch((renderError: unknown) => {
        if (!cancelled) {
          setSvg("");
          setError(renderError instanceof Error ? renderError.message : "Unable to render graph");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [cleaned, reactId]);

  if (error) {
    return (
      <div className={className}>
        <p className="mermaidError">{error}</p>
        <pre className="mermaidSource">{cleaned}</pre>
      </div>
    );
  }

  if (!svg) {
    return <div className={`${className ?? ""} mermaidPending`.trim()}>Rendering graph…</div>;
  }

  return <div className={className} dangerouslySetInnerHTML={{ __html: svg }} />;
}

function hashString(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(index);
    hash |= 0;
  }
  return hash;
}

export default MermaidDiagram;
