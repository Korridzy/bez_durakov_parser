import { createContext, type ReactNode, useContext, useState } from "react";
import { useLocation } from "react-router-dom";

import { Drawer } from "./Drawer";
import { useMediaQuery } from "./useMediaQuery";

const SidebarContext = createContext({
  narrow: false,
  open: false,
  setOpen: (_open: boolean) => {},
});

export function SidebarLayout({ children }: { readonly children: ReactNode }) {
  const narrow = useMediaQuery("(max-width: 900px)");
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const [scope, setScope] = useState({ pathname, narrow });
  // Mobile opening is transient; it never reads or writes ui.sidebarOpen.
  if (scope.pathname !== pathname || scope.narrow !== narrow) {
    setScope({ pathname, narrow });
    setOpen(false);
  }
  return (
    <SidebarContext.Provider value={{ narrow, open: narrow && open, setOpen }}>
      {children}
    </SidebarContext.Provider>
  );
}

export function useSidebarLayout() {
  return useContext(SidebarContext);
}

export function SidebarToggle() {
  const { narrow, open, setOpen } = useSidebarLayout();
  const { pathname } = useLocation();
  if (!narrow || !pathname.startsWith("/chats")) return null;
  return (
    <button
      type="button"
      className="button button-secondary sidebar-toggle"
      aria-expanded={open}
      aria-controls="sidebar-drawer"
      onClick={() => setOpen(!open)}
    >
      Чаты
    </button>
  );
}

export function SidebarSurface({ children }: { readonly children: ReactNode }) {
  const { narrow, open, setOpen } = useSidebarLayout();
  return (
    <Drawer name="sidebar" label="Список чатов" closeLabel="Закрыть список чатов"
      inline={!narrow} open={open} onClose={() => setOpen(false)}>
      <div className="sidebar-content" onClickCapture={(event) => {
        if (event.target instanceof Element &&
          event.target.closest(".chat-row-link, .chat-new-button")) setOpen(false);
      }}>
        {children}
      </div>
    </Drawer>
  );
}
