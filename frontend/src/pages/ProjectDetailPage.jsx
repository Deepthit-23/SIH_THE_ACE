import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import ExplanationList, { ScoreHeadline } from "../components/ExplanationList";
import { ErrorBox, Loading } from "../components/StateMessage";
import { formatINR, text, titleCase } from "../lib/format";

function Fact({ label, children }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-800">{children}</dd>
    </div>
  );
}

export default function ProjectDetailPage() {
  const { id } = useParams();
  const { status, data, error, reload } = useAsync(() => api.project(id), [id]);

  return (
    <div className="space-y-5">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-ink">
        ← Back to risk list
      </Link>

      {status === "loading" && <Loading label="Loading project…" />}
      {status === "error" && <ErrorBox error={error} onRetry={reload} />}

      {status === "success" && data && (
        <>
          <div className="rounded border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-2xl">
                <p className="text-xs text-slate-400">
                  Work ID {text(data.external_id, "—")} ·{" "}
                  {titleCase(data.status)} · {data.source_file ? text(data.source_file) : ""}
                </p>
                <h2 className="mt-1 text-lg font-semibold text-slate-900">
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
              <Fact label="District">{text(data.district)}</Fact>
              <Fact label="Category">{titleCase(data.derived_category) || "—"}</Fact>
              <Fact label="Sanctioned">{formatINR(data.sanctioned_amount)}</Fact>
              <Fact label="Final amount">{formatINR(data.final_amount)}</Fact>
              <Fact label="Recommended on">{text(data.recommendation_date)}</Fact>
              <Fact label="Completed on">{text(data.completion_date)}</Fact>
            </dl>
          </div>

          <div className="rounded border border-slate-200 bg-white p-5">
            <h3 className="text-sm font-semibold text-slate-800">Why this project was flagged</h3>
            <p className="mb-4 mt-1 text-xs text-slate-500">
              Ordered by contribution to the risk score. Each point is a separate
              signal — read together, not as a single verdict.
            </p>
            <ExplanationList items={data.explanation} />
          </div>
        </>
      )}
    </div>
  );
}
