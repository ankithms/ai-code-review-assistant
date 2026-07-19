type StatCardProps = {
  title: string;
  value: number | string;
};

export default function StatCard({
  title,
  value,
}: StatCardProps) {
  return (
    <div className="stat-card">
      <p className="stat-card__label">{title}</p>
      <p className="stat-card__value">{value}</p>
    </div>
  );
}
