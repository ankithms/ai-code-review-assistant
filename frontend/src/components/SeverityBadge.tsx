type Props = {
  severity: string;
};

export default function SeverityBadge({
  severity,
}: Props) {
  const normalized =
    severity.toLowerCase();

  return (
    <span className={`badge badge--${normalized}`}>
      {severity.toUpperCase()}
    </span>
  );
}
