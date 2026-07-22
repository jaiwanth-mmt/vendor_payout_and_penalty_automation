/**
 * App — route table only. JobProvider wraps /jobs/:jobId so poll+SSE survive stage nav.
 */
import { Route, Routes } from "react-router-dom";

import { JobProvider } from "./context/JobProvider";
import AppShell from "./layouts/AppShell";
import JobLayout from "./layouts/JobLayout";
import JobOutputsPage from "./pages/JobOutputsPage";
import JobProgressPage from "./pages/JobProgressPage";
import JobReviewPage from "./pages/JobReviewPage";
import NewJobPage from "./pages/NewJobPage";
import NotFoundPage from "./pages/NotFoundPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<NewJobPage />} />
        <Route
          path="jobs/:jobId"
          element={
            <JobProvider>
              <JobLayout />
            </JobProvider>
          }
        >
          <Route index element={<JobProgressPage />} />
          <Route path="review" element={<JobReviewPage />} />
          <Route path="outputs" element={<JobOutputsPage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
