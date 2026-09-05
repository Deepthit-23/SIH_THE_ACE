// Shared loading / empty / error panels.

export function Loading({ label = "Loading…" }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-slate-500">
      <span className="h-3 w-3 animate-pulse rounded-full bg-slate-400" />
      {label}
    </div>
  );
}

export function ErrorBox({ error, onRetry }) {
  return (
    <div className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-700">
      <p className="font-medium">Something went wrong</p>
      <p className="mt-1 text-red-600">{error}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 rounded border border-red-300 bg-white px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children = "Nothing to show." }) {
  return (
    <div className="rounded border border-slate-200 bg-white p-6 text-sm text-slate-500">
      {children}
    </div>
  );
}
