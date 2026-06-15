type Props = {
  severity: string;
};

export default function SeverityBadge({
  severity,
}: Props) {
  const normalized =
    severity.toLowerCase();

  let bg = "#22c55e";

  if (normalized === "high") {
    bg = "#ef4444";
  }

  if (normalized === "medium") {
    bg = "#f59e0b";
  }

  return (
    <span
      style={{
        background: bg,
        color: "white",
        padding: "4px 8px",
        borderRadius: "999px",
        fontSize: "12px",
      }}
    >
      {severity.toUpperCase()}
    </span>
  );
}