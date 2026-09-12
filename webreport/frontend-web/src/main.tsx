import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import { applyAccent, readAccent } from "./theme";
applyAccent(readAccent());
createRoot(document.getElementById("root")!).render(<App />);
