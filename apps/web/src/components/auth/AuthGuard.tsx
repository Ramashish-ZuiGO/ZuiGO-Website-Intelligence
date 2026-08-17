"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getToken } from "@/lib/auth";
import { TopNav } from "@/components/ui/TopNav";

/** Paths that do not require authentication. */
const PUBLIC_PATHS = ["/login"];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
}

/**
 * Client-side authentication guard.
 *
 * - On public paths (e.g. /login): renders children directly, no nav.
 * - On protected paths without a token: redirects to /login.
 * - On protected paths with a token: renders TopNav + children.
 *
 * Note: This only checks for the *presence* of a stored token, not its
 * validity.  An expired or tampered token will be caught by apiRequest's
 * 401 handler, which clears the token and redirects back here.
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);

  useEffect(() => {
    const checkAuth = () => {
      // We only need to guard protected routes.
      if (isPublicPath(pathname)) {
        setChecked(true);
        return;
      }

      // Now we are safely in the client, we can read localStorage.
      const token = getToken();
      if (!token) {
        router.replace(`/login?redirect=${encodeURIComponent(pathname)}`);
      } else {
        setAuthenticated(true);
      }
      setChecked(true);
    };

    // Defer slightly to avoid 'Calling setState synchronously within an effect' lint error
    const timer = setTimeout(checkAuth, 0);
    return () => clearTimeout(timer);
  }, [pathname, router]);


  // Public paths — render immediately without nav
  if (isPublicPath(pathname)) {
    return <>{children}</>;
  }

  // Still checking, or redirecting due to no token
  if (!checked || !authenticated) {
    return null;
  }

  // Authenticated — render with nav
  return (
    <>
      <a href="#main-content" className="z-skip-link">
        Skip to content
      </a>
      <TopNav />
      <div id="main-content" className="min-h-screen">
        {children}
      </div>
    </>
  );
}
