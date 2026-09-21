import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import ExplanationList, { ScoreHeadline } from "../components/ExplanationList";
import ScoreBreakdown from "../components/ScoreBreakdown";
import CasePanel from "../components/CasePanel";
import ProjectTimeline from "../components/ProjectTimeline";
import DuplicateComparison from "../components/DuplicateComparison";
import Meta from "../components/Meta";
import { ErrorBox, Loading } from "../components/StateMessage";
import { formatINR, text, titleCase } from "../lib/format";

function Fact({ label, children }) {
  return (
    <div>
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className="mt-0.5 text-sm text-ink">{children}</dd>
    </div>
  );
}

export default function ProjectDetailPage() {
  const { id } = useParams();
  const { status, data, error, reload } = useAsync(() => api.project(id), [id]);

  return (
    <div className="space-y-5">
      <Link to="/" className="text-sm text-ink-soft underline decoration-hairline underline-offset-4 hover:text-ink hover:decoration-ink">
        Back to the risk list
      </Link>

      {status === "loading" && <Loading label="Loading project…" />}
      {status === "error" && <ErrorBox error={error} onRetry={reload} />}

      {status === "success" && data && (
        <>
          <div className="rounded border border-hairline bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-2xl">
                <p className="text-xs text-ink-soft">
                  <Meta items={[<span>Work ID <span className="fig">{text(data.external_id, "-")}</span></span>, titleCase(data.status), data.source_file ? text(data.source_file) : null]} />
                </p>
                <h2 className="mt-1 text-lg font-semibold text-ink">
                  {text(data.work_description, "Untitled work")}
                </h2>
              </div>
              <ScoreHeadline score={data.combined_risk_score} />
            </div>

            <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-4">
              <Fact label="MP">{text(data.mp_name)}</Fact>
              <Fact label="Constituency">{text(data.constituency)}</Fact>
              <Fact label="House">{text(data.house)}</Fact>
              <Fact label="State">{text(data.state)}</Fact>
              {data.work_state && data.work_state !== data.state && (
                <Fact label="Work location">{data.work_state} <span className="text-xs text-ink-faint">(cross-state work)</span></Fact>
              )}
              <Fact label="District">{text(data.district)}</Fact>
              <Fact label="Category">{titleCase(data.derived_category) || "—"}</Fact>
              <Fact label="Sanctioned">{formatINR(data.sanctioned_amount)}</Fact>
              <Fact label="Final amount">{formatINR(data.final_amount)}</Fact>
              <Fact label="Recommended on">{text(data.recommendation_date)}</Fact>
              <Fact label="Completed on">{text(data.completion_date)}</Fact>
            </dl>
          </div>

          <ProjectTimeline project={data} />

          {data.explanation?.filter((e) => e.code === "duplicate_work" && e.counterpart_id).map((e) => (
            <DuplicateComparison key={e.counterpart_id} project={data} item={e} />
          ))}

          <div className="grid gap-5 lg:grid-cols-3">
            <div className="space-y-5 lg:col-span-2">
              <div className="rounded border border-hairline bg-surface p-5">
                <h3 className="text-sm font-semibold text-ink">Why this project was flagged</h3>
                <p className="mb-4 mt-1 text-xs text-ink-soft">
                  Ordered by contribution to the risk score. Each point is a separate
                  signal — read together, not as a single verdict.
                </p>
                <ExplanationList items={data.explanation} />
              </div>
              {(data.rule_flags && Object.values(data.rule_flags).some(Boolean)) || data.explanation?.length ? (
                <ScoreBreakdown
                  explanation={data.explanation}
                  ruleScore={data.rule_score}
                  mlScore={data.ml_score}
                  combined={data.combined_risk_score}
                />
              ) : null}
            </div>

            <CasePanel
              projectId={data.id}
              initialStatus={data.case_status}
              initialNote={data.case_note}
              updatedAt={data.case_updated_at}
            />
          </div>
        </>
      )}
    </div>
  );
}
