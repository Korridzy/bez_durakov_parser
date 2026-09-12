import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  ArrowUpRight,
  Database,
  Check,
  ChevronDown,
  Loader2,
  X,
} from "lucide-react";

export function Logo({ small = false }: { small?: boolean }) {
  return (
    <span className={"logo " + (small ? "small" : "")}>
      <svg viewBox="0 0 36 36" fill="none" aria-hidden="true">
        <path
          d="M11 10h13M11 10v16h9a6 6 0 0 0 0-12h-4"
          stroke="currentColor"
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="25.5" cy="9.5" r="3" className="logo-dot" />
      </svg>
    </span>
  );
}
export function ProviderIcon({
  id,
  large = false,
}: {
  id: string;
  large?: boolean;
}) {
  const icons: Record<string, string> = {
    metrika: "metrika.png",
    ga4: "ga4.svg",
    matomo: "matomo.png",
    amplitude: "amplitude.png",
    mixpanel: "mixpanel.png",
    posthog: "posthog.svg",
  };
  return (
    <span
      className={"provider-icon " + id + (large ? " large" : "")}
      aria-hidden="true"
    >
      {icons[id] ? (
        <img src={"/providers/" + icons[id]} alt="" />
      ) : (
        <Database size={large ? 24 : 17} />
      )}
    </span>
  );
}
export function Spinner({ label }: { label?: string }) {
  return (
    <span className="loading">
      <Loader2 className="spin" size={16} />
      {label}
    </span>
  );
}
export function Alert({ children }: { children: ReactNode }) {
  return (
    <div className="error-notice" role="alert">
      {children}
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
  fullscreen = false,
  actions,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
  fullscreen?: boolean;
  actions?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return createPortal(
    <dialog
      ref={ref}
      className={
        "modal " + (wide ? "wide " : "") + (fullscreen ? "fullscreen" : "")
      }
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) {
          const r = ref.current.getBoundingClientRect();
          if (
            e.clientX < r.left ||
            e.clientX > r.right ||
            e.clientY < r.top ||
            e.clientY > r.bottom
          )
            onClose();
        }
      }}
    >
      <header className="modal-header">
        <h2>{title}</h2>
        <div className="inline">
          {actions}
          <button
            className="icon-button"
            aria-label="Закрыть"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
      </header>
      {children}
    </dialog>,
    document.body,
  );
}
export function Menu({
  label,
  children,
  open,
  onToggle,
  onClose,
  className = "",
  ariaLabel,
}: {
  label: ReactNode;
  children: ReactNode;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  className?: string;
  ariaLabel: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const pointer = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
      }
      if (
        ["ArrowDown", "ArrowUp"].includes(e.key) &&
        ref.current?.contains(document.activeElement)
      ) {
        e.preventDefault();
        const b = Array.from(
          ref.current.querySelectorAll<HTMLButtonElement>(
            ".menu button:not(:disabled)",
          ),
        );
        const index = b.indexOf(document.activeElement as HTMLButtonElement);
        b[
          (index + (e.key === "ArrowDown" ? 1 : -1) + b.length) % b.length
        ]?.focus();
      }
    };
    document.addEventListener("pointerdown", pointer);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", pointer);
      document.removeEventListener("keydown", key);
    };
  }, [open, onClose]);
  return (
    <div className={"menu-anchor " + className} ref={ref}>
      <button
        className="menu-trigger"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={onToggle}
      >
        {label}
      </button>
      {open && (
        <div className="menu" role="menu">
          {children}
        </div>
      )}
    </div>
  );
}
export function SelectLabel({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <ChevronDown size={14} />
    </>
  );
}
export function MenuItem({
  children,
  selected,
  onClick,
  disabled = false,
}: {
  children: ReactNode;
  selected?: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      role="menuitem"
      className="menu-item"
      onClick={onClick}
      disabled={disabled}
    >
      {children}
      {selected && <Check size={16} />}
    </button>
  );
}
export function ExternalLink({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <a className="text-link" href={href} target="_blank" rel="noreferrer">
      {children}
      <ArrowUpRight size={14} />
    </a>
  );
}
