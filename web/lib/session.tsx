"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { Role, Session } from "./api";

/**
 * Who you are signed in as, and what that lets you reach.
 *
 * The roles here mirror the server's grant table exactly, because the whole
 * point of this system is the disclosure boundary and a console that let you
 * *see* something the API would refuse would be lying about it. So the UI hides
 * nothing it cannot also prove: every console page still calls the API, and a
 * role that should not have it gets a real 403 from the server rather than a
 * blank screen from the client.
 *
 * In a deployment this is Keycloak and a bearer token. Here it is a chooser,
 * because a demonstration has to be able to put on each hat in turn — and the
 * REPLAY-only header shim it drives is refused outright once the process is
 * pointed at live records.
 */

export interface Actor {
  role: Role;
  operator: string;
  units: string;
  title: string;
  who: string;
  /** What this actor can reach. Mirrors the server's (role, purpose) grants. */
  routes: string[];
  canSee: string[];
  cannotSee: string[];
  accent: string;
}

export const ACTORS: Actor[] = [
  {
    role: "welfare_officer",
    operator: "WO-12",
    units: "UNIT-01,UNIT-02",
    title: "Welfare Officer",
    who: "Maj. R. Sharma · Welfare cell, UNIT-01 and UNIT-02",
    routes: ["/officer"],
    canSee: [
      "Escalated cases in your own units, with identity on request",
      "The gate arithmetic, the drivers, and the case against",
      "A recommended intervention, and a mandatory close-out",
    ],
    cannotSee: [
      "Anyone under MONITOR — no name is produced at all",
      "Raw self-assessment answers, ever",
      "Cases in a unit you are not responsible for",
    ],
    accent: "var(--accent)",
  },
  {
    role: "commander",
    operator: "CO-01",
    units: "UNIT-01",
    title: "Commanding Officer",
    who: "Col. A. Menon · Officer Commanding, UNIT-01",
    routes: ["/unit"],
    canSee: [
      "Unit fatigue and workload heat maps, for rebalancing rosters",
      "Aggregates covering at least five personnel, with noise added",
    ],
    cannotSee: [
      "Any individual, ever — there is no drill-down and no API that answers one",
      "The welfare caseload",
      "Another unit's view",
    ],
    accent: "var(--mid)",
  },
  {
    role: "personnel",
    operator: "SELF",
    units: "",
    title: "Personnel",
    who: "A jawan or officer, viewing their own record",
    routes: ["/me"],
    canSee: [
      "Your own consent, in your own language, with one-tap withdrawal",
      "The wellness self-assessment, if you choose to take it",
      "Why the system looked at you — the same reasons the officer got",
    ],
    cannotSee: [
      "Anybody else's anything",
      "The caseload, the unit view, or the ledger",
    ],
    accent: "var(--pass)",
  },
  {
    role: "auditor",
    operator: "AU-03",
    units: "",
    title: "Auditor",
    who: "Governance and audit · force-wide",
    routes: ["/audit"],
    canSee: [
      "The full hash-chained ledger — every access, verdict, override and consent change",
      "The differential-privacy budget consumed",
      "That a person withdrew consent — and you are the only one who can",
    ],
    cannotSee: [
      "The content of anything — only that an event occurred",
      "An identity. Reading the ledger never resolves a pid",
    ],
    accent: "var(--hold)",
  },
];

const STORAGE_KEY = "samvedna.actor";

interface SessionValue {
  actor: Actor | null;
  session: Session | null;
  signIn: (role: Role) => void;
  signOut: () => void;
  ready: boolean;
  /** Every actor, for the chooser and the "what others see" panels. */
  actors: Actor[];
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<Role | null>(null);
  const [ready, setReady] = useState(false);

  // Read after mount, so the server and first client render agree and the page
  // does not flash a role nobody chose.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored && ACTORS.some((a) => a.role === stored)) {
        setRole(stored as Role);
      }
    } catch {
      /* private browsing; the chooser still works for this session */
    }
    setReady(true);
  }, []);

  const signIn = useCallback((next: Role) => {
    setRole(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* the choice still applies for this session */
    }
  }, []);

  const signOut = useCallback(() => {
    setRole(null);
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* nothing to clear */
    }
  }, []);

  const value = useMemo<SessionValue>(() => {
    const actor = ACTORS.find((a) => a.role === role) ?? null;
    return {
      actor,
      session: actor
        ? { role: actor.role, operator: actor.operator, units: actor.units }
        : null,
      signIn,
      signOut,
      ready,
      actors: ACTORS,
    };
  }, [role, signIn, signOut, ready]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside a SessionProvider");
  return context;
}

export function actorFor(role: Role): Actor | undefined {
  return ACTORS.find((a) => a.role === role);
}
