import type { MindChangeItem } from "@/lib/types";

/**
 * What would change our mind.
 *
 * Every line here was computed by inverting a gate, never generated. That is why
 * each one names a number an officer can check rather than saying "more data
 * would help" — and why this panel is shown for MONITOR cases rather than being
 * hidden as an internal detail. A system that declines to name somebody owes
 * the officer an account of what it was waiting for.
 */
export function MindChange({ items }: { items: MindChangeItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="card" style={{ marginTop: 18 }}>
      <h3>What would change our mind</h3>
      <p className="faint" style={{ marginTop: 0 }}>
        Computed by inverting each failed gate. Every item is checkable.
      </p>
      <div className="stack">
        {items.map((item) => (
          <div key={item.gate} className="card flat tight">
            <div className="row">
              <strong>{item.gate}</strong>
              <span className="mono faint">
                {item.current.toFixed(3)} → needs {item.required.toFixed(2)}
              </span>
              <span className={`pill ${item.recoverable ? "accent" : "stop"}`}>
                {item.recoverable ? "recoverable" : "not recoverable this cycle"}
              </span>
            </div>
            <ul className="faint" style={{ margin: "8px 0 4px", paddingInlineStart: 18 }}>
              {item.failed_because.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            <ul style={{ margin: "4px 0 0", paddingInlineStart: 18 }}>
              {item.would_change_if.map((change) => (
                <li key={change} style={{ color: "var(--ink)" }}>
                  {change}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
