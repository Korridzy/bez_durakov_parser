import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { CalendarDays, ChevronDown, RefreshCw } from "lucide-react";
import { dayLabel } from "./api";
import { DateRangeCalendar } from "./DateRangeCalendar";
import {
  localDate,
  matchingPreset,
  periodPresets,
  presetDates,
  type ReportDates,
} from "./report-period";

function rangeLabel({ date1, date2 }: ReportDates) {
  const first = dayLabel(date1),
    last = dayLabel(date2);
  const year1 = date1.slice(0, 4),
    year2 = date2.slice(0, 4);
  if (year1 !== year2) return `${first} ${year1} — ${last} ${year2}`;
  const range = date1 === date2 ? first : `${first} — ${last}`;
  return year1 === String(new Date().getFullYear())
    ? range
    : `${range} ${year1}`;
}

export function ReportPeriod({
  dates,
  onChange,
  loading,
  onRefresh,
  today = localDate(new Date()),
  children,
}: {
  dates: ReportDates;
  onChange: (dates: ReportDates) => void;
  loading: boolean;
  onRefresh: () => void;
  today?: string;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [calendarTop, setCalendarTop] = useState(120);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const selected = matchingPreset(dates, new Date(today + "T12:00:00"));
  const activeIndex = periodPresets.findIndex(({ id }) => id === selected);

  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open]);

  return (
    <div className="report-toolbar" aria-label="Период отчёта">
      <div
        className="period-presets"
        role="group"
        aria-label="Быстрый выбор периода"
      >
        <span
          className="period-highlight"
          aria-hidden="true"
          style={{
            transform: `translateX(${Math.max(0, activeIndex) * 100}%)`,
            opacity: activeIndex < 0 ? 0 : 1,
          }}
        >
          <span key={selected} className="period-highlight-glint" />
        </span>
        {periodPresets.map(({ id, label, hint }) => (
          <button
            key={id}
            type="button"
            aria-pressed={selected === id}
            title={hint}
            onClick={() => {
              onChange(presetDates(id, new Date(today + "T12:00:00")));
              setOpen(false);
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        className="period-calendar"
        ref={root}
        onKeyDown={(event) => {
          if (event.key === "Escape" && open) {
            event.preventDefault();
            event.stopPropagation();
            setOpen(false);
            trigger.current?.focus();
          }
        }}
        onBlur={(event) => {
          if (
            event.relatedTarget &&
            !event.currentTarget.contains(event.relatedTarget as Node)
          )
            setOpen(false);
        }}
      >
        <button
          ref={trigger}
          type="button"
          className={"period-range " + (!selected ? "custom" : "")}
          aria-label={`Выбрать даты: ${rangeLabel(dates)}`}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => {
            setCalendarTop(
              (trigger.current?.getBoundingClientRect().bottom || 108) + 12,
            );
            setOpen(!open);
          }}
        >
          <CalendarDays size={15} />
          <span>{rangeLabel(dates)}</span>
          <ChevronDown size={14} className={open ? "rotated" : ""} />
        </button>
        {open && (
          <div
            id={panelId}
            className="calendar-popover"
            role="dialog"
            aria-label="Выбор диапазона дат"
            style={
              { "--calendar-top": calendarTop + "px" } as React.CSSProperties
            }
          >
            <DateRangeCalendar
              dates={dates}
              today={today}
              onApply={(next) => {
                onChange(next);
                setOpen(false);
                trigger.current?.focus();
              }}
              onCancel={() => {
                setOpen(false);
                trigger.current?.focus();
              }}
            />
          </div>
        )}
      </div>
      {children}
      <button
        className="icon-button report-refresh"
        type="button"
        aria-label="Обновить данные"
        disabled={loading}
        onClick={onRefresh}
      >
        <RefreshCw size={16} className={loading ? "spin" : ""} />
      </button>
    </div>
  );
}
