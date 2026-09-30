import {
  createContext, type ReactNode, useContext, useEffect, useLayoutEffect, useRef, useState,
} from "react";

import { useReports } from "../reports/ReportsContext";
import { ReportsPanel } from "../reports/ReportsPanel";
import { Drawer } from "./Drawer";
import { useSidebarLayout } from "./SidebarLayout";
import { useMediaQuery } from "./useMediaQuery";

const ReportsLayoutContext = createContext({
  compact: false, open: false, toggle: () => {},
});

export function ReportsToggle({ count }: { readonly count: number }) {
  const { compact, open, toggle } = useContext(ReportsLayoutContext);
  if (!compact) return null;
  return (
    <button
      type="button"
      className="button button-secondary reports-toggle"
      aria-controls="reports-drawer"
      aria-expanded={open}
      onClick={toggle}
    >
      Отчёты ({count})
    </button>
  );
}

export function ChatLayout({ children }: { readonly children: ReactNode }) {
  const compact = useMediaQuery("(max-width: 1199px)");
  const { open: sidebarOpen } = useSidebarLayout();
  const { chatId, openReportId } = useReports();
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState({ chatId, compact, sidebarOpen });
  const root = useRef<HTMLDivElement>(null);
  const active = compact && open && !sidebarOpen;

  if (scope.chatId !== chatId || scope.compact !== compact || scope.sidebarOpen !== sidebarOpen) {
    setScope({ chatId, compact, sidebarOpen });
    setOpen(false);
  }
  useEffect(() => {
    if (openReportId !== null) setOpen(true);
  }, [openReportId]);

  useLayoutEffect(() => {
    const element = root.current;
    const bar = element?.querySelector(".chat-composer-bar");
    if (!active || element === null || !bar) return;
    const measure = () => element.style.setProperty(
      "--composer-height", `${bar.getBoundingClientRect().height}px`,
    );
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(bar);
    return () => observer.disconnect();
  }, [active]);

  return (
    <ReportsLayoutContext.Provider value={{ compact, open: active, toggle: () => setOpen(!open) }}>
      <div className="chat-view" ref={root} onClickCapture={(event) => {
        // Also reopen an already-selected report after the drawer was dismissed.
        if (event.target instanceof Element && event.target.closest(".msg__report-chip")) {
          setOpen(true);
        }
      }}>
        <section className="chat-main" aria-label="Диалог">{children}</section>
        <Drawer name="reports" label="Отчёты чата" closeLabel="Закрыть отчёты"
          inline={!compact} open={active} onClose={() => setOpen(false)} companion={root}>
          <ReportsPanel />
        </Drawer>
      </div>
    </ReportsLayoutContext.Provider>
  );
}
