type Props = {
  status: string;
};

export default function StatusBadge({ status }: Props) {
  const normalized = status.toUpperCase();

  return (
    <span className={`badge badge--${normalized.toLowerCase()}`}>
      {normalized}
    </span>
  );
}
