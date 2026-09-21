/** A line of related facts, separated by hairlines instead of middle dots or pipes:
 *  <Meta items={["Work 311094", "Recommended", "Health facility"]} />
 *  Falsy items are skipped, so callers don't have to build strings. */
export default function Meta({ items, className = "" }) {
  const shown = items.filter((x) => x !== null && x !== undefined && x !== false && x !== "");
  return (
    <span className={`inline-flex flex-wrap items-center ${className}`}>
      {shown.map((x, i) => (
        <span key={i} className={i ? "ml-2.5 border-l border-hairline pl-2.5" : ""}>{x}</span>
      ))}
    </span>
  );
}
