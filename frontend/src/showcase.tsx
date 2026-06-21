import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import { DesignSystemShowcase } from "./design-system/showcase/DesignSystemShowcase";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <DesignSystemShowcase />
  </React.StrictMode>,
);
