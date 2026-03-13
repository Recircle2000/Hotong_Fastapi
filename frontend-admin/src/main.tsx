import "@toast-ui/editor/dist/toastui-editor.css";
import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { AuthProvider } from "./auth/AuthProvider";
import "./styles.css";
import { ToastProvider } from "./toast/ToastProvider";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ToastProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </ToastProvider>
  </React.StrictMode>,
);
