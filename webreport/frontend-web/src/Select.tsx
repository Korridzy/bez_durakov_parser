import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";

type Option = { value: string; label: string; icon?: ReactNode };

export function Select({
  id,
  label,
  value,
  options,
  onChange,
  disabled = false,
}: {
  id: string;
  label: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const search = useRef({ text: "", at: 0 });
  const selected = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );
  const choose = (index: number) => {
    onChange(options[index].value);
    setOpen(false);
  };
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  useEffect(() => {
    if (open)
      root.current
        ?.querySelector(`#${id}-option-${active}`)
        ?.scrollIntoView({ block: "nearest" });
  }, [open, active, id]);
  return (
    <div className="custom-select" ref={root}>
      <button
        id={id}
        type="button"
        role="combobox"
        aria-label={label}
        aria-haspopup="listbox"
        aria-controls={open ? id + "-options" : undefined}
        aria-expanded={open}
        aria-activedescendant={open ? `${id}-option-${active}` : undefined}
        className="select-trigger"
        disabled={disabled}
        onClick={() => {
          setActive(selected);
          setOpen(!open);
        }}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => {
          const key = event.key;
          if (key === "Escape" && open) {
            event.preventDefault();
            event.stopPropagation();
            setOpen(false);
          } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(key)) {
            event.preventDefault();
            setOpen(true);
            setActive(
              key === "Home"
                ? 0
                : key === "End"
                  ? options.length - 1
                  : !open
                    ? selected
                    : Math.max(
                        0,
                        Math.min(
                          options.length - 1,
                          active + (key === "ArrowDown" ? 1 : -1),
                        ),
                      ),
            );
          } else if (key === "Enter" || key === " ") {
            event.preventDefault();
            if (open) choose(active);
            else {
              setActive(selected);
              setOpen(true);
            }
          } else if (key === "Tab" && open) {
            choose(active);
          } else if (
            key.length === 1 &&
            !event.ctrlKey &&
            !event.metaKey &&
            !event.altKey
          ) {
            event.preventDefault();
            const text =
              (Date.now() - search.current.at < 700
                ? search.current.text
                : "") + key.toLocaleLowerCase();
            search.current = { text, at: Date.now() };
            const prefix = [...text].every((letter) => letter === text[0])
              ? text[0]
              : text;
            const start = open ? active : selected;
            const index = options.findIndex((_, offset) =>
              options[(start + offset + 1) % options.length].label
                .toLocaleLowerCase()
                .startsWith(prefix),
            );
            setOpen(true);
            if (index >= 0) setActive((start + index + 1) % options.length);
          }
        }}
      >
        {options[selected]?.icon}
        <span>{options[selected]?.label}</span>
        <ChevronDown size={16} className={open ? "rotated" : ""} />
      </button>
      {open && (
        <div
          id={id + "-options"}
          role="listbox"
          aria-label={label}
          className="select-options"
        >
          {options.map((option, index) => (
            <div
              id={`${id}-option-${index}`}
              key={option.value}
              role="option"
              aria-selected={value === option.value}
              className={"select-option " + (active === index ? "focused" : "")}
              onPointerDown={(event) => event.preventDefault()}
              onPointerMove={() => setActive(index)}
              onClick={() => choose(index)}
            >
              {option.icon}
              <span>{option.label}</span>
              {value === option.value && <Check size={16} />}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
