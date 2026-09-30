import { type ReactNode, type RefObject, useEffect, useRef } from "react";

interface DrawerProps {
  readonly name: "sidebar" | "reports";
  readonly label: string;
  readonly closeLabel: string;
  readonly inline: boolean;
  readonly open: boolean;
  readonly onClose: () => void;
  readonly children: ReactNode;
  /** Reports include the composer in their focus scope, never making it inert. */
  readonly companion?: RefObject<HTMLElement | null>;
}

const FOCUSABLE =
  'a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"])';

export function Drawer({
  name, label, closeLabel, inline, open, onClose, children, companion,
}: DrawerProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dismiss = useRef(onClose);
  dismiss.current = onClose;
  const active = open && !inline;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!active || dialog === null) return;
    // Closing reports during a sidebar handoff restores their opener before
    // this effect runs; the sidebar must still return to its own top-bar control.
    const opener = name === "sidebar"
      ? document.querySelector('[aria-controls="sidebar-drawer"]')
      : document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus({ preventScroll: true });

    const companionElement = () => companion?.current?.querySelector(".chat-composer-bar");
    const inside = (node: Node) => dialog.contains(node) || companionElement()?.contains(node);
    const onFocus = (event: FocusEvent) => {
      if (event.target instanceof Node && !inside(event.target)) {
        closeRef.current?.focus({ preventScroll: true });
      }
    };
    const onKey = (event: KeyboardEvent) => {
      // A nested native fullscreen dialog owns its own Escape and tab order.
      if (event.defaultPrevented || (
        event.target instanceof Element &&
        event.target.closest("dialog") !== null &&
        event.target.closest("dialog") !== dialog
      )) return;
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss.current();
      } else if (event.key === "Tab") {
        const candidates = [
          ...dialog.querySelectorAll<HTMLElement>(FOCUSABLE),
          ...(companionElement()?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []),
        ].filter((element) =>
          element.tabIndex >= 0 &&
          !element.matches(":disabled") &&
          !element.closest("[hidden], [inert], dialog:not([open])") &&
          getComputedStyle(element).display !== "none" &&
          getComputedStyle(element).visibility !== "hidden"
        );
        // The composer precedes the dialog in DOM order. Drive the whole
        // combined cycle, not just its ends, so Tab can cross that boundary.
        const index = candidates.findIndex((element) => element === document.activeElement);
        const step = event.shiftKey ? -1 : 1;
        event.preventDefault();
        candidates[(index + step + candidates.length) % candidates.length]?.focus();
      }
    };
    document.addEventListener("focusin", onFocus);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("focusin", onFocus);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      if (opener instanceof HTMLElement && opener.isConnected) {
        opener.focus({ preventScroll: true });
      }
    };
  }, [active, companion, name]);

  return (
    <div
      className={`drawer-surface drawer-surface--${name}${inline ? " is-inline" : ""}`}
      hidden={!inline && !open}
    >
      {!inline && open ? (
        <div
          className="drawer-backdrop"
          data-testid={`${name}-backdrop`}
          aria-hidden="true"
          onClick={onClose}
        />
      ) : null}
      <dialog
        ref={dialogRef}
        id={`${name}-drawer`}
        className={`drawer drawer--${name}`}
        open={inline || open}
        role={inline ? "presentation" : undefined}
        aria-label={inline ? undefined : label}
        aria-modal={active && companion === undefined ? true : undefined}
        onCancel={(event) => { event.preventDefault(); onClose(); }}
      >
        {!inline ? (
          <div className="drawer__head">
            <span className="drawer__title">{label}</span>
            <button ref={closeRef} type="button" className="button button-secondary" onClick={onClose}>
              {closeLabel}
            </button>
          </div>
        ) : null}
        {children}
      </dialog>
    </div>
  );
}
