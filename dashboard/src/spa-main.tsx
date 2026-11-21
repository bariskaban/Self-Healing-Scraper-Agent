import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Inter ships in the bundle: the page makes no request to a font host or CDN.
import "@fontsource-variable/inter";
import "./styles.css";
import App from "./App";
import { PagesRoot } from "./components/pages/PagesRoot";

// PagesRoot owns the hash routes #/tv, #/scale and #/tenders; every other route is App's.
createRoot(document.getElementById("root")!).render(<StrictMode><PagesRoot><App /></PagesRoot></StrictMode>);
