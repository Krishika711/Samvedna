import type { Caseload } from "@/lib/types";

/**
 * Degradation is shown at the top of the caseload, not buried in a status page.
 *
 * The invariant in PART 8.8 is that every degradation makes the system say
 * *less*. An officer who does not know a connector failed will read a short
 * caseload as good news, which is the one misreading that matters.
 */
export function RunBanners({ run }: { run: Caseload }) {
  return (
    <>
      {run.escalation_frozen && (
        <div className="banner stop">
          <strong>Escalation frozen.</strong>
          <span>
            {run.freeze_reason} No case has been named in this run. MONITOR
            records are still being kept.
          </span>
        </div>
      )}
      {run.degraded_connectors.length > 0 && (
        <div className="banner warn">
          <strong>Run incomplete.</strong>
          <span>
            {run.degraded_connectors.join(", ")} returned partial or no records.
            Those domains are excluded from the evidence — nothing has been
            imputed to cover the gap, so this caseload is shorter than a complete
            run would produce.
          </span>
        </div>
      )}
      {run.unavailable_reviewers.length > 0 && !run.escalation_frozen && (
        <div className="banner warn">
          <strong>Reviewer unavailable:</strong>
          <span>{run.unavailable_reviewers.join(", ")}.</span>
        </div>
      )}
    </>
  );
}
