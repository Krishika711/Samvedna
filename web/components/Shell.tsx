"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useSession } from "@/lib/session";

/**
 * The role bar and the role-aware navigation.
 *
 * Two rules, and the second is the one that matters:
 *
 * **The nav shows only what this actor can reach.** Not because hiding is
 * security — it is not — but because a menu offering a page the server will
 * refuse teaches the operator that the system is arbitrary.
 *
 * **The refusal is still real.** `Guard` below does not silently redirect. It
 * says which role you are, which role the page needs, and offers to switch —
 * so a demonstration can *show* the boundary rather than route around it. The
 * server refuses independently in every case; this is the explanation, not the
 * enforcement.
 */

const PUBLIC = [
  { href: "/", label: "Overview" },
];

const ADDON = { href: "/voice", label: "Voice" };

const ROUTE_LABEL: Record<string, string> = {
  "/officer": "Caseload",
  "/unit": "Unit strain",
  "/me": "My data",
  "/audit": "Assurance",
};

export function RoleBar() {
  const { actor, signOut, ready } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  if (!ready) return null;

  if (!actor) {
    return (
      <div className="rolebar rolebar-out">
        <div className="rolebar-inner">
          <span className="faint">Not signed in — viewing the public overview.</span>
          <span className="spacer" />
          <Link href="/signin" className="pill accent" style={{ padding: "5px 13px" }}>
            Sign in →
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="rolebar" style={{ borderBottomColor: actor.accent }}>
      <div className="rolebar-inner">
        <span className="rolebar-dot" style={{ background: actor.accent }} />
        <span>
          Signed in as <strong>{actor.title}</strong>
          <span className="faint"> · {actor.operator}</span>
          {actor.units && <span className="faint"> · scoped to {actor.units}</span>}
        </span>
        <span className="spacer" />
        <Link href="/signin" className="faint">
          Switch role
        </Link>
        <button
          className="ghost"
          style={{ padding: "3px 11px", fontSize: "0.82rem" }}
          onClick={() => {
            signOut();
            if (pathname !== "/") router.push("/");
          }}
        >
          Sign out
        </button>
      </div>
    </div>
  );
}

export function Nav() {
  const pathname = usePathname();
  const { actor, ready } = useSession();

  const mine = ready && actor ? actor.routes : [];

  const item = (href: string, label: string, extra?: string) => {
    const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
    return (
      <Link
        key={href}
        href={href}
        className={extra}
        aria-current={active ? "page" : undefined}
      >
        {label}
        {extra === "nav-addon" && <span className="nav-tag">add-on</span>}
      </Link>
    );
  };

  return (
    <nav className="nav" aria-label="Primary">
      {PUBLIC.map((p) => item(p.href, p.label))}
      {mine.map((href) => item(href, ROUTE_LABEL[href] ?? href))}
      {/* The run is not a walkthrough any more, so it is not labelled as one.
        * It is the one link that is useful signed in as anybody. */}
      <Link href="/demo" aria-current={pathname === "/demo" ? "page" : undefined}>
        Tonight&rsquo;s run
      </Link>
      <span className="nav-divider" aria-hidden="true" />
      {item(ADDON.href, ADDON.label, "nav-addon")}
    </nav>
  );
}

/**
 * Wraps a console page. Explains a refusal rather than hiding the page.
 */
export function Guard({
  need,
  children,
}: {
  need: string;
  children: React.ReactNode;
}) {
  const { actor, ready, actors, signIn } = useSession();
  const router = useRouter();
  const wanted = actors.find((a) => a.role === need);

  if (!ready) return <p className="faint" style={{ paddingTop: 34 }}>…</p>;

  if (!actor) {
    return (
      <div className="page-head">
        <p className="eyebrow">Not signed in</p>
        <h1>This console needs a role</h1>
        <p className="lede">
          {wanted?.title} is the only role that can reach this page. Pick a role
          to continue.
        </p>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="primary" onClick={() => router.push("/signin")}>
            Choose a role
          </button>
        </div>
      </div>
    );
  }

  if (actor.role !== need) {
    return (
      <>
        <div className="page-head">
          <p className="eyebrow">Refused</p>
          <h1>A {actor.title} cannot open this</h1>
          <p className="lede">
            This is the {wanted?.title} console. You are signed in as{" "}
            {actor.title}, and the server refuses the underlying request for that
            role — this page is not merely hidden from you.
          </p>
        </div>

        <div className="grid grid-2">
          <div className="card" style={{ borderTop: `4px solid ${actor.accent}` }}>
            <h3>What you can see as {actor.title}</h3>
            <ul className="muted" style={{ paddingInlineStart: 18, marginTop: 8 }}>
              {actor.canSee.map((l) => <li key={l}>{l}</li>)}
            </ul>
            <div className="row" style={{ marginTop: 14 }}>
              <button className="primary" onClick={() => router.push(actor.routes[0])}>
                Go to my console
              </button>
            </div>
          </div>
          <div className="card" style={{ borderTop: `4px solid ${wanted?.accent}` }}>
            <h3>What a {wanted?.title} sees here</h3>
            <ul className="muted" style={{ paddingInlineStart: 18, marginTop: 8 }}>
              {wanted?.canSee.map((l) => <li key={l}>{l}</li>)}
            </ul>
            <div className="row" style={{ marginTop: 14 }}>
              <button
                onClick={() => {
                  signIn(need as never);
                }}
              >
                Switch to {wanted?.title}
              </button>
            </div>
          </div>
        </div>

        <div className="banner info" style={{ marginTop: 18 }}>
          <strong>This is the point, not an obstacle.</strong>
          <span>
            The disclosure boundary is enforced in the software, not in the
            interface. A bug in this console could not leak a name, because the
            API would never have returned one.
          </span>
        </div>
      </>
    );
  }

  return <>{children}</>;
}
