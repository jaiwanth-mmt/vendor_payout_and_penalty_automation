/**
 * NotFoundPage — unknown routes.
 */
import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div className="pageFrame">
      <div className="emptyState pageEmpty">
        <strong>Page not found</strong>
        <Link className="ghostButton" to="/">
          Start a new job
        </Link>
      </div>
    </div>
  );
}
