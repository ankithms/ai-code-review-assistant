import { ArrowRight, GitBranch } from "lucide-react";

type PullRequestBranchFlowProps = {
  repository?: string | null;
  sourceBranch?: string | null;
  sourceRepository?: string | null;
  targetBranch?: string | null;
  detail?: boolean;
};

export default function PullRequestBranchFlow({
  repository,
  sourceBranch,
  sourceRepository,
  targetBranch,
  detail = false,
}: PullRequestBranchFlowProps) {
  const className = `branch-flow${detail ? " branch-flow--detail" : ""}`;
  if (!sourceBranch || !targetBranch) {
    return <span className={`${className} branch-flow--unavailable`}>Branch details unavailable</span>;
  }

  const sourceLabel = sourceRepository && sourceRepository !== repository
    ? `${sourceRepository}:${sourceBranch}`
    : sourceBranch;

  return (
    <div className={className} aria-label={`Merging ${sourceLabel} into ${targetBranch}`}>
      <GitBranch aria-hidden="true" size={detail ? 14 : 13} />
      <code title={sourceLabel}>{sourceLabel}</code>
      <ArrowRight aria-hidden="true" className="branch-flow__arrow" size={detail ? 14 : 13} />
      <code title={targetBranch}>{targetBranch}</code>
    </div>
  );
}
