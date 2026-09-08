"use client";

import { useRouter } from "next/navigation";
import { useSession } from "@/lib/session";

/**
 * Choose who you are.
 *
 * In a deployment this is Keycloak and a bearer token carrying a role and a
 * unit scope. Here it is a chooser, because the thing this system has to be
 * able to demonstrate is the *boundary* — what each actor can and cannot reach —
 * and you cannot show a boundary from one side of it.
 *
 * Each card states what that actor can and cannot see before you pick it, so
 * the boundary is legible before anybody has signed in. Those lists are not
 * marketing: they are the server's grant table, and every one of them is
 * enforced by a 403 rather than by a hidden menu item.
 */
export default function SignIn() {
  const { actors, signIn, actor: current } = useSession();
  const router = useRouter();

  const enter = (role: string, route: string) => {
    signIn(role as never);
    router.push(route);
  };

  return (
    <>
      <div className="page-head">
        <p className="eyebrow">Sign in · REPLAY demonstration</p>
        <h1>Who are you?</h1>
        <p className="lede">
          This system is defined by what each person cannot see. Pick a role to
          enter its console — then try to reach another one, and watch the server
          refuse rather than the menu hide it.
        </p>
      </div>

      {current && (
        <div className="banner info">
          <strong>Currently signed in as {current.title}.</strong>
          <span>Choosing another role switches you; nothing is carried across.</span>
        </div>
      )}

      <div className="grid grid-2" style={{ marginTop: 18 }}>
        {actors.map((a) => (
          <div
            className="card lifted"
            key={a.role}
            style={{ borderTop: `4px solid ${a.accent}` }}
          >
            <div className="row" style={{ marginBottom: 4 }}>
              <h2 style={{ fontSize: "1.25rem" }}>{a.title}</h2>
              <span className="spacer" />
              {current?.role === a.role && <span className="pill accent">signed in</span>}
            </div>
            <p className="faint" style={{ marginBottom: 14 }}>{a.who}</p>

            <h3 style={{ fontSize: "0.82rem", color: "var(--pass)" }}>CAN SEE</h3>
            <ul className="muted" style={{ paddingInlineStart: 18, margin: "6px 0 14px" }}>
              {a.canSee.map((line) => <li key={line}>{line}</li>)}
            </ul>

            <h3 style={{ fontSize: "0.82rem", color: "var(--stop)" }}>CANNOT SEE</h3>
            <ul className="faint" style={{ paddingInlineStart: 18, margin: "6px 0 16px" }}>
              {a.cannotSee.map((line) => <li key={line}>{line}</li>)}
            </ul>

            <button className="primary" onClick={() => enter(a.role, a.routes[0])}>
              Enter as {a.title}
            </button>
          </div>
        ))}
      </div>

      <div className="card flat" style={{ marginTop: 22 }}>
        <h3>Why a chooser and not a password</h3>
        <p className="muted" style={{ marginTop: 8 }}>
          The header-based identity this drives is a REPLAY-only development
          shim standing where OIDC goes, and the API returns{" "}
          <code>501 Not Implemented</code> for it the moment the process is
          pointed at live records. It cannot survive being deployed, which is the
          only property that makes it safe to ship in the repository.
        </p>
      </div>
    </>
  );
}
