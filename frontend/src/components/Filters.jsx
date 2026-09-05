import { titleCase } from "../lib/format";

const SELECT =
  "rounded border border-slate-300 bg-white px-2 py-1.5 text-sm focus:border-slate-400 focus:outline-none";

export default function Filters({ value, options, onChange, onReset }) {
  const set = (patch) => onChange({ ...value, ...patch, offset: 0 });

  return (
    <div className="flex flex-wrap items-end gap-3 rounded border border-slate-200 bg-white p-3">
      <label className="flex flex-col gap-1 text-xs text-slate-500">
        Minimum score
        <div className="flex items-center gap-2">
          <input
            type="range"
            min="0"
            max="100"
            step="5"
            value={value.min_score ?? 0}
            onChange={(e) => set({ min_score: Number(e.target.value) || undefined })}
            className="w-32"
          />
          <span className="w-6 text-sm font-medium text-slate-700">
            {value.min_score ?? 0}
          </span>
        </div>
      </label>

      <label className="flex flex-col gap-1 text-xs text-slate-500">
        Category
        <select
          className={SELECT}
          value={value.derived_category ?? ""}
          onChange={(e) => set({ derived_category: e.target.value || undefined })}
        >
          <option value="">All</option>
          {(options?.derived_categories ?? []).map((c) => (
            <option key={c} value={c}>
              {titleCase(c)}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs text-slate-500">
        State
        <select
          className={SELECT}
          value={value.state ?? ""}
          onChange={(e) => set({ state: e.target.value || undefined })}
        >
          <option value="">All</option>
          {(options?.states ?? []).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs text-slate-500">
        Status
        <select
          className={SELECT}
          value={value.status ?? ""}
          onChange={(e) => set({ status: e.target.value || undefined })}
        >
          <option value="">All</option>
          <option value="recommended">Recommended</option>
          <option value="completed">Completed</option>
        </select>
      </label>

      <button
        onClick={onReset}
        className="ml-auto rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
      >
        Reset
      </button>
    </div>
  );
}
