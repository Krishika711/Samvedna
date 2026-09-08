"use client";

import { useState } from "react";
import type { Gate } from "@/lib/types";

/**
 * Four bars, and on click each one reveals the formula with the actual numbers
 * substituted.
 *
 * This is the element that converts "the computer says 0.694" into a decision an
 * officer can defend to the jawan sitting opposite them. The formula is not a
 * debugging affordance behind a developer flag — it is the product. So it is a
 * click rather than a hover: hover does not exist on the tablets these are read
 * on, and an officer being asked "why me?" needs it on the screen, not under a
 * cursor.
 */
export function GatePanel({ gates, open = false }: { gates: Gate[]; open?: boolean }) {
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(open ? gates.map((g) => g.name) : []),
  );

  const toggle = (name: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  return (
    <div>
      {gates.map((gate) => {
        const isOpen = expanded.has(gate.name);
        return (
          <div className="gate" key={gate.name}>
            <button
              className="gate-btn"
              onClick={() => toggle(gate.name)}
              aria-expanded={isOpen}
            >
              <div className="gate-line">
                <span className="gate-label">{gate.name}</span>
                <span className="track">
                  <span
                    className={`fill ${gate.passed ? "pass" : "hold"}`}
                    style={{ width: `${Math.round(gate.value * 100)}%` }}
                  />
                  <span
                    className="thresh"
                    style={{ left: `${Math.round(gate.threshold * 100)}%` }}
                    title={`threshold ${gate.threshold}`}
                  />
                </span>
                <span className={`gate-num ${gate.passed ? "pass" : "hold"}`}>
                  {gate.value.toFixed(3)}
                </span>
                <span className="gate-of">/{gate.threshold.toFixed(2)}</span>
                <span className="gate-hint">
                  {isOpen ? "hide working" : "show working"}
                </span>
              </div>
            </button>
            {isOpen && (
              <>
                <div className="gate-formula">{gate.formula}</div>
                <table style={{ marginTop: 8 }}>
                  <tbody>
                    {Object.entries(gate.inputs)
                      .filter(([, v]) => v !== "")
                      .map(([key, value]) => (
                        <tr key={key}>
                          <td className="faint" style={{ width: 180 }}>
                            {key}
                          </td>
                          <td className="mono">{value}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
