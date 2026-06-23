import { Navigate } from "react-router-dom";

/**
 * Legacy operator entry point. Keeping the component as a redirect prevents
 * future route changes from restoring the old full-list polling dashboard.
 */
export function Dashboard() {
  return <Navigate to="/app" replace />;
}
