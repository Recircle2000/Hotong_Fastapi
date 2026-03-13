import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "./components/ProtectedRoute";
import { EmergencyNoticePage } from "./pages/EmergencyNoticePage";
import { LoginPage } from "./pages/LoginPage";
import { NoticesPage } from "./pages/NoticesPage";
import { ShuttlePage } from "./pages/ShuttlePage";

export function App() {
  return (
    <BrowserRouter basename="/admin-v2">
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route index element={<Navigate to="/notices" replace />} />
          <Route path="/emergency-notices" element={<EmergencyNoticePage />} />
          <Route path="/notices" element={<NoticesPage />} />
          <Route path="/shuttle" element={<ShuttlePage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
