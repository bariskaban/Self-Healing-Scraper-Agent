import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Inter ships in the bundle: the page makes no request to a font host or CDN.
import "@fontsource-variable/inter";
import "./styles.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
