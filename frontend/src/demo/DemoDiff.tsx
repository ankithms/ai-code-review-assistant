type DiffLine = { text: string; kind: "file" | "hunk" | "added" | "removed" | "context"; oldNumber: number | null; newNumber: number | null };

function classify(text: string): DiffLine["kind"] {
  if (!text) return "file";
  if (text.startsWith("@@")) return "hunk";
  if (text.startsWith("+")) return "added";
  if (text.startsWith("-")) return "removed";
  if (text && !text.startsWith(" ")) return "file";
  return "context";
}

export default function DemoDiff({ diff }: { diff: string }) {
  const lines = parseDiff(diff);

  return (
    <div className="demo-diff" aria-label="Sample code diff">
      {lines.map((line, index) => (
        <div className={`demo-diff__line demo-diff__line--${line.kind}`} key={`${index}-${line.text}`}>
          <span className="demo-diff__number">{line.oldNumber}</span>
          <span className="demo-diff__number">{line.newNumber}</span>
          <code>{line.text || " "}</code>
        </div>
      ))}
    </div>
  );
}

function parseDiff(diff: string): DiffLine[] {
  let oldLine = 0;
  let newLine = 0;
  return diff.split("\n").map((text) => {
    const kind = classify(text);
    const match = kind === "hunk" ? text.match(/@@ -(\d+)(?:,\d+)? \+(\d+)/) : null;
    if (match) {
      oldLine = Number(match[1]);
      newLine = Number(match[2]);
    }
    const oldNumber = kind === "removed" || kind === "context" ? oldLine++ : null;
    const newNumber = kind === "added" || kind === "context" ? newLine++ : null;
    return { text, kind, oldNumber, newNumber };
  });
}
