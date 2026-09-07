import { BrowserRouter, Route, Routes, useParams } from "react-router-dom";

import { HomePage } from "@/pages/HomePage";
import { WorkspacePage } from "@/pages/WorkspacePage";

function WorkspaceRoute() {
  const { tripId } = useParams();
  return <WorkspacePage key={tripId} />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/new" element={<WorkspacePage />} />
      <Route path="/trips/:tripId" element={<WorkspaceRoute />} />
    </Routes>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}

export default App;
