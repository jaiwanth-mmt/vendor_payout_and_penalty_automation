/**
 * AppShell — brand topbar + outlet. Live job status lives in JobLayout.
 */
import { Link, Outlet, useLocation } from "react-router-dom";

export default function AppShell() {
  const { pathname } = useLocation();
  const onJobRoute = pathname.startsWith("/jobs/");

  return (
    <div className="appShell">
      <header className="topbar">
        <Link className="brandLockup brandLink" to="/">
          <div className="brandMark" aria-hidden="true">
            <span />
            <span />
          </div>
          <div>
            <p className="eyebrow">MakeMyTrip cab ops</p>
            <h1>Agentic Loss Recovery Copilot</h1>
          </div>
        </Link>
        {!onJobRoute && (
          <div className="statusPill" data-state="idle">
            <span>ready</span>
          </div>
        )}
      </header>
      <Outlet />
    </div>
  );
}
