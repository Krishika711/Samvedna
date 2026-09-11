"use client";

import { useEffect, useState } from "react";

/**
 * The service this deployment serves, and the words it uses.
 *
 * India's uniformed services do not share a rank ladder or an echelon
 * vocabulary. An Army company sits inside a battalion inside a brigade; an Air
 * Force flight sits inside a squadron inside a wing; a Navy division sits
 * inside a ship. Hardcoding "Battalion" into a console makes it wrong for
 * seven of the eleven services this system models, and a welfare officer shown
 * the wrong word for their own formation trusts the rest of the screen less.
 *
 * Read from `/api/service`, which is public — the console needs these words
 * before it can render anything, so gating them behind a role would mean the
 * sign-in screen itself could not be labelled.
 */

export interface ServiceInfo {
  code: string;
  abbr: string;
  name: string;
  ministry: string;
  sub_unit: string;
  unit: string;
  formation: string;
  personnel_word: string;
  personnel_plural: string;
  ranks: string[];
  postings: string[];
  catalogue: {
    code: string;
    abbr: string;
    name: string;
    ministry: string;
    unit: string;
  }[];
}

/** Neutral words, used only until the real ones arrive. Never force-specific:
 *  a wrong-but-plausible label is worse than an obviously generic one. */
const PENDING: ServiceInfo = {
  code: "",
  abbr: "",
  name: "Uniformed service",
  ministry: "",
  sub_unit: "Sub-unit",
  unit: "Unit",
  formation: "Formation",
  personnel_word: "personnel",
  personnel_plural: "personnel",
  ranks: [],
  postings: [],
  catalogue: [],
};

export function useService(): { service: ServiceInfo; ready: boolean } {
  const [service, setService] = useState<ServiceInfo>(PENDING);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    fetch("/api/service")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: ServiceInfo) => { setService(d); setReady(true); })
      .catch(() => { /* keep the neutral words; the console still works */ });
  }, []);

  return { service, ready };
}
