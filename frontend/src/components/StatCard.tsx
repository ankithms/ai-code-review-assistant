import type { LucideIcon } from "lucide-react";
import { ArrowUpRight } from "lucide-react";
import { Link, useInRouterContext } from "react-router-dom";

type StatCardProps = {
  title: string;
  value: number | string;
  detail?: string;
  icon?: LucideIcon;
  tone?: "accent" | "success" | "warning" | "danger" | "neutral";
  href?: string;
};

export default function StatCard({
  title,
  value,
  detail,
  icon: Icon,
  tone = "neutral",
  href,
}: StatCardProps) {
  const inRouter = useInRouterContext();
  const content = (
    <>
      <div className="stat-card__topline">
        {Icon && (
          <span className="stat-card__icon" aria-hidden="true">
            <Icon size={18} strokeWidth={2.1} />
          </span>
        )}
        {href && <ArrowUpRight className="stat-card__arrow" aria-hidden="true" size={17} />}
      </div>
      <p className="stat-card__value">{value}</p>
      <p className="stat-card__label">{title}</p>
      {detail && <p className="stat-card__detail">{detail}</p>}
    </>
  );

  return href && inRouter ? (
    <Link className={`stat-card stat-card--${tone}`} to={href}>
      {content}
    </Link>
  ) : (
    <div className={`stat-card stat-card--${tone}`}>
      {content}
    </div>
  );
}
