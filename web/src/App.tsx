import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { BillingAlerts } from "./components/BillingHud";
import StagePage from "./pages/StagePage";
import TasksPage from "./pages/TasksPage";
import TagsPage from "./pages/TagsPage";
import TelegramPage from "./pages/TelegramPage";
import SettingsPage from "./pages/SettingsPage";
import { useI18n } from "./i18n/context";
import { highlightPanel } from "./panelFocus";
import { isShellDialog, openShellDialog } from "./shellDialogs";

function HashFlash() {
  const location = useLocation();
  const skipInitialHash = useRef(true);

  useEffect(() => {
    const id = location.hash.replace(/^#/, "");
    if (skipInitialHash.current) {
      skipInitialHash.current = false;
      return;
    }
    if (!id) return;
    if (isShellDialog(id)) {
      openShellDialog(id);
      return;
    }
    highlightPanel(id);
  }, [location.hash]);

  return null;
}

export default function App() {
  const { m } = useI18n();
  return (
    <div className="app-shell">
      <HashFlash />
      <a className="skip-link" href="#main">
        {m.skip}
      </a>
      <BillingAlerts />
      <main id="main" className="page-gutter app-main-pad">
        <StagePage taskPanel={<TasksPage />} />
      </main>
      <TelegramPage />
      <TagsPage />
      <SettingsPage />
    </div>
  );
}
