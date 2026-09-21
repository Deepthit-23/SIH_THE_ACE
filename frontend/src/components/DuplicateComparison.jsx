import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import { formatINR, text, titleCase } from "../lib/format";

const amountOf = (p) => Number(p.sanctioned_amount ?? p.final_amount ?? p.amount ?? NaN);
const eventDate = (p) => p.completion_date || p.recommendation_date;

/** Word-level diff (LCS) so the reader can see WHAT differs between two near-identical descriptions.
 *  Returns two token arrays with a `diff` flag on words that are not in the common subsequence. */
export function diffWords(a, b) {
  const A = String(a ?? "").split(/\s+/).filter(Boolean);
  const B = String(b ?? "").split(/\s+/).filter(Boolean);
  const norm = (w) => w.toLowerCase().replace(/[^a-z0-9]/g, "");
  const dp = Array.from({ length: A.length + 1 }, () => new Array(B.length + 1).fill(0));
  for (let i = A.length - 1; i >= 0; i--)
    for (let j = B.length - 1; j >= 0; j--)
      dp[i][j] = norm(A[i]) === norm(B[j]) ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const outA = A.map((w) => ({ w, diff: true }));
  const outB = B.map((w) => ({ w, diff: true }));
  let i = 0, j = 0;
  while (i < A.length && j < B.length) {
    if (norm(A[i]) === norm(B[j])) { outA[i].diff = false; outB[j].diff = false; i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) i++;
    else j++;
  }
  return [outA, outB];
}

function Words({ tokens }) {
  return (
    <p className="text-sm leading-relaxed text-ink">
      {tokens.map((t, i) => (
        <span key={i} className={t.diff ? "rounded bg-medium/10 px-0.5" : ""}>{t.w}{" "}</span>
      ))}
    </p>
  );
}

function Row({ label, children }) {
  return (
    <div className="grid grid-cols-[6.5rem_1fr] gap-2 border-t border-hairline py-2 first:border-t-0">
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className="text-sm text-ink">{children}</dd>
    </div>
  );
}

function Panel({ title, tag, p, tokens, highlight }) {
  return (
    <div className={`rounded border bg-surface p-4 ${highlight ? "border-hairline" : "border-hairline"}`}>
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-xs font-semibold text-ink-soft">{title}</h4>
        {tag}
      </div>
      <dl>
        <Row label="Description"><Words tokens={tokens} /></Row>
        <Row label="Amount">{formatINR(amountOf(p))}</Row>
        <Row label="Recommended">{text(p.recommendation_date)}</Row>
        <Row label="Completed">{text(p.completion_date)}</Row>
        <Row label="Status">{titleCase(p.status)}</Row>
        <Row label="Work ID">{text(p.external_id)}</Row>
        <Row label="Location">{text(p.constituency)}, {text(p.district)}</Row>
      </dl>
    </div>
  );
}

/** Two-panel comparison of a duplicate-flagged project and the counterpart the rule matched it with. */
export default function DuplicateComparison({ project, item }) {
  const { status, data: other, error } = useAsync(() => api.project(item.counterpart_id), [item.counterpart_id]);

  const a = amountOf(project);
  const b = other ? amountOf(other) : NaN;
  const amtGap = Number.isFinite(a) && Number.isFinite(b) && Math.max(a, b) > 0
    ? (Math.abs(a - b) / Math.max(a, b)) * 100 : null;
  const da = eventDate(project) ? new Date(eventDate(project)) : null;
  const db = other && eventDate(other) ? new Date(eventDate(other)) : null;
  const dayGap = da && db ? Math.round(Math.abs(da - db) / 86_400_000) : null;
  const [ta, tb] = other ? diffWords(project.work_description, other.work_description) : [[], []];

  return (
    <div className="rounded border border-hairline bg-surface p-5" data-testid="duplicate-comparison">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">Possible duplicate — side by side</h3>
        {other && (
          <Link to={`/projects/${item.counterpart_id}`} className="text-xs text-ink-soft underline hover:text-ink">
            Open counterpart, project {item.counterpart_id}
          </Link>
        )}
      </div>
      <p className="mb-4 mt-1 text-xs text-ink-soft">
        The rule matched this work to another recorded for the same MP and constituency. Highlighted words differ.
        Repeat purchases can be legitimate; this is a prompt to check, not a finding.
      </p>

      {status === "loading" && <p className="p-4 text-sm text-ink-soft">Loading counterpart…</p>}

      {status === "error" && (
        <div className="rounded border border-hairline bg-canvas p-4 text-sm text-ink-soft">
          <p className="font-medium">The matched counterpart (project {item.counterpart_id}) is not available to your account.</p>
          <p className="mt-1 text-xs text-ink-soft">
            {String(error).includes("403") ? "It sits outside your authorised scope. " : ""}
            Text similarity recorded by the rule: <b>{item.similarity}%</b>.
          </p>
        </div>
      )}

      {status === "success" && other && (
        <div className="grid items-start gap-3 lg:grid-cols-[1fr_9rem_1fr]">
          <Panel title="This project" p={project} tokens={ta}
            tag={<span className="rounded bg-ink px-1.5 py-0.5 text-[11px] text-surface">#{project.id}</span>} highlight />
          <div className="flex flex-row items-center justify-center gap-4 lg:flex-col lg:pt-10">
            <div className="text-center">
              <p className="text-3xl font-semibold tabular-nums text-ink">{item.similarity}%</p>
              <p className="text-[11px] text-ink-faint">text similarity</p>
            </div>
            <dl className="space-y-1 text-center text-xs text-ink-soft">
              <div><dt className="inline">Amount gap </dt><dd className="inline font-medium text-ink">{amtGap === null ? "—" : `${amtGap.toFixed(1)}%`}</dd></div>
              <div><dt className="inline">Date gap </dt><dd className="inline font-medium text-ink">{dayGap === null ? "—" : `${dayGap} days`}</dd></div>
            </dl>
          </div>
          <Panel title="Matched counterpart" p={other} tokens={tb}
            tag={<span className="rounded bg-canvas px-1.5 py-0.5 text-[11px] text-ink-soft">#{other.id}</span>} />
        </div>
      )}
    </div>
  );
}
