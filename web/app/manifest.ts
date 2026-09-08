import type { MetadataRoute } from "next";

/**
 * Installable web app manifest — the "secure mobile application" the problem
 * statement asks for.
 *
 * A web app rather than a store app, and that is a deployment decision rather
 * than a shortcut. Two reasons:
 *
 * **It can be hosted inside the force's own network.** A store app has to pass
 * through Apple's and Google's review and distribution, which means the binary
 * and its update channel sit outside the organisation. A jawan installing this
 * from an internal URL is installing something the force controls end to end.
 *
 * **There is one codebase and one consent text.** The consent screen is
 * legally load-bearing — consent is recorded against a specific text at a
 * specific version — and maintaining three implementations of it across web,
 * iOS and Android is three chances for them to disagree about what somebody
 * agreed to.
 *
 * `display: standalone` is what makes it open without browser chrome once
 * added to a home screen, which is the difference between something that feels
 * like an app and a bookmark.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "SAMVEDNA — Personnel Wellness",
    short_name: "SAMVEDNA",
    description:
      "Your wellness check-in, what this system can see about you, and your consent — in your own language.",
    // Deep-links straight to the personnel app rather than the landing page.
    // Somebody who installed this on their phone did so to use their own
    // console, not to read about the system.
    start_url: "/me",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    // Matches --brand-deep and --brand-tint in globals.css. If those change,
    // these follow; a status bar in last season's colour is the sort of detail
    // that makes an app feel unmaintained.
    background_color: "#F0F3F7",
    theme_color: "#16243D",
    lang: "en",
    dir: "auto",
    categories: ["health", "productivity"],
    icons: [
      {
        // Inline SVG data URI, so there is no binary asset to lose in transfer
        // and nothing to fetch at install time. A maskable SVG scales to every
        // launcher size from one source.
        src:
          "data:image/svg+xml," +
          encodeURIComponent(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">' +
              '<rect width="512" height="512" rx="96" fill="#16243D"/>' +
              // Four bars, shortest to tallest: the four gates, three clear and
              // one short. The icon is the product.
              '<rect x="120" y="300" width="44" height="92" rx="8" fill="#F0F3F7"/>' +
              '<rect x="192" y="248" width="44" height="144" rx="8" fill="#F0F3F7"/>' +
              '<rect x="264" y="196" width="44" height="196" rx="8" fill="#F0F3F7"/>' +
              '<rect x="336" y="272" width="44" height="120" rx="8" fill="#E0571C"/>' +
              '<rect x="120" y="128" width="260" height="10" rx="5" fill="#E0571C" opacity="0.55"/>' +
              "</svg>",
          ),
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any",
      },
    ],
  };
}
