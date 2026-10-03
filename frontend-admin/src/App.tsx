import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AdminLayout } from "./components/AdminLayout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { EmergencyNoticePage } from "./pages/EmergencyNoticePage";
import { LoginPage } from "./pages/LoginPage";
import { NoticesPage } from "./pages/NoticesPage";
import { ShuttlePage } from "./pages/ShuttlePage";
import { ShuttleStationsPage } from "./pages/ShuttleStationsPage";
import { TaxiLocationsPage } from "./pages/TaxiLocationsPage";
import { TaxiPartiesPage } from "./pages/TaxiPartiesPage";
import { TaxiReportsPage } from "./pages/TaxiReportsPage";
import { TaxiSanctionsPage } from "./pages/TaxiSanctionsPage";
import { ShuttleTimetablePage } from "./pages/ShuttleTimetablePage";

export function App() {
  return (
    <BrowserRouter basename="/admin-v2">
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AdminLayout />}>
            <Route index element={<Navigate to="/notices" replace />} />
            <Route path="/emergency-notices" element={<EmergencyNoticePage />} />
            <Route path="/notices" element={<NoticesPage />} />
            <Route path="/shuttle" element={<ShuttlePage />} />
            <Route path="/shuttle/timetable" element={<ShuttleTimetablePage />} />
            <Route path="/shuttle-stations" element={<ShuttleStationsPage />} />
            <Route path="/taxi-locations" element={<TaxiLocationsPage />} />
            <Route path="/taxi-parties" element={<TaxiPartiesPage />} />
            <Route path="/taxi-reports" element={<TaxiReportsPage />} />
            <Route path="/taxi-sanctions" element={<TaxiSanctionsPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
