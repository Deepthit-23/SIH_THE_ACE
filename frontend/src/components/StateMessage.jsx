// Shared loading / empty / error states. Static: the only animation in the tool is the sign-in count-up.

export function Loading({ label = "Loading…" }) {
  return <p className="py-6 text-sm text-ink-faint">{label}</p>;
}

export function ErrorBox({ error, onRetry }) {
  return (
    <div className="border-l-[3px] border-high bg-high/10 px-4 py-3 text-sm">
      <p className="font-semibold text-ink">Something went wrong</p>
      <p className="mt-0.5 text-ink-soft">{error}</p>
      {onRetry && (
        <button onClick={onRetry} className="btn mt-2">
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children = "Nothing to show." }) {
  return <p className="border border-dashed border-hairline px-4 py-6 text-sm text-ink-soft">{children}</p>;
}
