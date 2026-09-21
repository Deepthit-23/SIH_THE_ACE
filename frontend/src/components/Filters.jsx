import { titleCase } from "../lib/format";

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="label">{label}</span>
      {children}
    </label>
  );
}

/** Filter controls as one hairline-ruled row. Fields use the shared `field` treatment; nothing is boxed twice. */
export default function Filters({ value, options, onChange, onReset, lead = null }) {
  const set = (patch) => onChange({ ...value, ...patch, offset: 0 });

  return (
    <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
      {lead}
      <Field label="Minimum score">
        <span className="flex h-[38px] items-center gap-3">
          <input
            type="range"
            min="0"
            max="100"
            step="5"
            value={value.min_score ?? 0}
            onChange={(e) => set({ min_score: Number(e.target.value) || undefined })}
            className="w-32 accent-ink"
          />
          <span className="fig w-7 text-right text-sm">{value.min_score ?? 0}</span>
        </span>
      </Field>

      <Field label="Category">
        <select className="field w-40" value={value.derived_category ?? ""} onChange={(e) => set({ derived_category: e.target.value || undefined })}>
          <option value="">All</option>
          {(options?.derived_categories ?? []).map((c) => (
            <option key={c} value={c}>{titleCase(c)}</option>
          ))}
        </select>
      </Field>

      <Field label="State of work">
        <select className="field w-40" value={value.state ?? ""} onChange={(e) => set({ state: e.target.value || undefined })}>
          <option value="">All</option>
          {(options?.states ?? []).map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </Field>

      <Field label="Work status">
        <select className="field w-36" value={value.status ?? ""} onChange={(e) => set({ status: e.target.value || undefined })}>
          <option value="">All</option>
          <option value="recommended">Recommended</option>
          <option value="completed">Completed</option>
        </select>
      </Field>

    </div>
  );
}
