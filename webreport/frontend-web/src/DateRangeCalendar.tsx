import { useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";
import { localDate, periodError, type ReportDates } from "./report-period";
import "./date-calendar.css";

const parseDay = (day: string) => new Date(day + "T12:00:00");
const shiftMonth = (day: string, offset: number) => {
  const date = parseDay(day);
  return localDate(
    new Date(date.getFullYear(), date.getMonth() + offset, 1, 12),
  );
};
const displayDay = (day: string) => day.split("-").reverse().join(".");
function typedDay(text: string) {
  const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(text.trim());
  if (!match) return "";
  const day = `${match[3]}-${match[2]}-${match[1]}`;
  return localDate(parseDay(day)) === day ? day : "";
}

export function DateRangeCalendar({
  dates,
  today,
  onApply,
  onCancel,
}: {
  dates: ReportDates;
  today: string;
  onApply: (dates: ReportDates) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(dates);
  const [texts, setTexts] = useState([
    displayDay(dates.date1),
    displayDay(dates.date2),
  ]);
  const [selectingEnd, setSelectingEnd] = useState(false);
  const [hovered, setHovered] = useState("");
  const [preferredCount, setPreferredCount] = useState(3);
  const [width, setWidth] = useState(innerWidth);
  const count = Math.min(
    preferredCount,
    width < 680 ? 1 : width < 960 ? 2 : width < 1220 ? 3 : 4,
  );
  const [firstMonth, setFirstMonth] = useState(() =>
    shiftMonth(dates.date2, -(count - 1)),
  );
  const [focused, setFocused] = useState(dates.date2);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const resize = () => setWidth(innerWidth);
    addEventListener("resize", resize);
    root.current
      ?.querySelector<HTMLButtonElement>(`[data-day="${dates.date2}"]`)
      ?.focus();
    return () => removeEventListener("resize", resize);
  }, []);
  const update = (value: ReportDates) => {
    setDraft(value);
    setTexts([displayDay(value.date1), displayDay(value.date2)]);
  };
  const choose = (day: string) => {
    if (!selectingEnd) {
      update({ date1: day, date2: day });
      setSelectingEnd(true);
    } else {
      update({
        date1: day < draft.date1 ? day : draft.date1,
        date2: day < draft.date1 ? draft.date1 : day,
      });
      setSelectingEnd(false);
    }
    setHovered("");
    setFocused(day);
  };
  const previewEnd = selectingEnd && hovered ? hovered : draft.date2;
  const start = draft.date1 < previewEnd ? draft.date1 : previewEnd;
  const end = draft.date1 < previewEnd ? previewEnd : draft.date1;
  const validTexts = { date1: typedDay(texts[0]), date2: typedDay(texts[1]) };
  const error =
    !validTexts.date1 || !validTexts.date2
      ? "Введите даты в формате ДД.ММ.ГГГГ."
      : periodError(validTexts, today);
  const keyboard = (
    event: React.KeyboardEvent<HTMLButtonElement>,
    day: string,
  ) => {
    const offsets: Record<string, number> = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -7,
      ArrowDown: 7,
    };
    let next = parseDay(day);
    if (event.key in offsets) next.setDate(next.getDate() + offsets[event.key]);
    else if (event.key === "Home")
      next.setDate(next.getDate() - ((next.getDay() + 6) % 7));
    else if (event.key === "End")
      next.setDate(next.getDate() + 6 - ((next.getDay() + 6) % 7));
    else if (event.key === "PageUp" || event.key === "PageDown") {
      const step = event.key === "PageUp" ? -1 : 1;
      const month = new Date(next.getFullYear(), next.getMonth() + step, 1, 12);
      month.setDate(
        Math.min(
          next.getDate(),
          new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate(),
        ),
      );
      next = month;
    } else return;
    event.preventDefault();
    const value = localDate(next);
    if (value > today) return;
    setFocused(value);
    if (value < firstMonth) setFirstMonth(shiftMonth(value, 0));
    if (value >= shiftMonth(firstMonth, count))
      setFirstMonth(shiftMonth(value, -(count - 1)));
    requestAnimationFrame(() =>
      root.current
        ?.querySelector<HTMLButtonElement>(`[data-day="${value}"]`)
        ?.focus(),
    );
  };
  const months = Array.from({ length: count }, (_, index) =>
    shiftMonth(firstMonth, index),
  );
  const tabbableDay =
    focused >= firstMonth && focused < shiftMonth(firstMonth, count)
      ? focused
      : firstMonth;
  return (
    <div
      className="range-calendar"
      ref={root}
      style={{ "--calendar-months": count } as React.CSSProperties}
    >
      <header className="calendar-toolbar">
        <div>
          <strong>Выберите диапазон</strong>
          <span>
            {selectingEnd
              ? "Теперь выберите последний день"
              : "Нажмите первый и последний день"}
          </span>
        </div>
        {width >= 960 && (
          <div className="calendar-density" aria-label="Количество месяцев">
            {[2, 3, 4]
              .filter((n) => width >= 1220 || n < 4)
              .map((n) => (
                <button
                  type="button"
                  key={n}
                  aria-pressed={preferredCount === n}
                  onClick={() => {
                    setPreferredCount(n);
                    setFirstMonth(shiftMonth(draft.date2, -(n - 1)));
                  }}
                >
                  {n} мес.
                </button>
              ))}
          </div>
        )}
      </header>
      <div className="calendar-navigation">
        <button
          type="button"
          className="icon-button"
          aria-label="На год назад"
          onClick={() => setFirstMonth(shiftMonth(firstMonth, -12))}
        >
          <ChevronsLeft size={17} />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="Предыдущий месяц"
          onClick={() => setFirstMonth(shiftMonth(firstMonth, -1))}
        >
          <ChevronLeft size={17} />
        </button>
        <button
          type="button"
          className="calendar-today"
          onClick={() => setFirstMonth(shiftMonth(today, -(count - 1)))}
        >
          К текущему месяцу
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="Следующий месяц"
          disabled={shiftMonth(firstMonth, count) > today}
          onClick={() => setFirstMonth(shiftMonth(firstMonth, 1))}
        >
          <ChevronRight size={17} />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="На год вперёд"
          disabled={shiftMonth(firstMonth, count + 11) > today}
          onClick={() => setFirstMonth(shiftMonth(firstMonth, 12))}
        >
          <ChevronsRight size={17} />
        </button>
      </div>
      <div className="calendar-months" onMouseLeave={() => setHovered("")}>
        {months.map((month) => {
          const date = parseDay(month),
            year = date.getFullYear(),
            monthIndex = date.getMonth();
          const blanks = (date.getDay() + 6) % 7,
            days = new Date(year, monthIndex + 1, 0).getDate();
          return (
            <section
              className="calendar-month"
              key={month}
              aria-label={date.toLocaleDateString("ru-RU", {
                month: "long",
                year: "numeric",
              })}
            >
              <h4>
                {date
                  .toLocaleDateString("ru-RU", {
                    month: "long",
                    year: "numeric",
                  })
                  .replace(" г.", "")}
              </h4>
              <div className="calendar-weekdays">
                {["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((day) => (
                  <span key={day}>{day}</span>
                ))}
              </div>
              <div className="calendar-days">
                {Array.from({ length: blanks }, (_, n) => (
                  <span key={`blank-${n}`} />
                ))}
                {Array.from({ length: days }, (_, n) => {
                  const day = localDate(new Date(year, monthIndex, n + 1, 12));
                  return (
                    <button
                      key={day}
                      data-day={day}
                      type="button"
                      disabled={day > today}
                      tabIndex={tabbableDay === day ? 0 : -1}
                      aria-label={parseDay(day).toLocaleDateString("ru-RU", {
                        day: "numeric",
                        month: "long",
                        year: "numeric",
                      })}
                      aria-pressed={day >= start && day <= end}
                      aria-current={day === today ? "date" : undefined}
                      className={[
                        day === start ? "range-start" : "",
                        day === end ? "range-end" : "",
                        day > start && day < end ? "in-range" : "",
                        day === today ? "is-today" : "",
                      ].join(" ")}
                      onFocus={() => setFocused(day)}
                      onKeyDown={(event) => keyboard(event, day)}
                      onClick={() => choose(day)}
                      onMouseEnter={() => selectingEnd && setHovered(day)}
                    >
                      {n + 1}
                    </button>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
      <form
        className="calendar-footer"
        onSubmit={(event) => {
          event.preventDefault();
          if (!error) onApply(validTexts);
        }}
      >
        <div className="calendar-text-inputs">
          {["Начало периода", "Конец периода"].map((label, index) => (
            <label key={label}>
              <span>{label}</span>
              <input
                aria-label={label}
                inputMode="numeric"
                placeholder="ДД.ММ.ГГГГ"
                value={texts[index]}
                maxLength={10}
                onChange={(event) => {
                  const next = [...texts];
                  next[index] = event.target.value;
                  setTexts(next);
                  const parsed = typedDay(event.target.value);
                  if (parsed)
                    setDraft((d) => ({
                      ...d,
                      [index === 0 ? "date1" : "date2"]: parsed,
                    }));
                  setSelectingEnd(false);
                }}
              />
            </label>
          ))}
        </div>
        <span
          className={"calendar-period-length " + (error ? "invalid" : "")}
          role="status"
        >
          {error ||
            `${Math.round((Date.parse(validTexts.date2) - Date.parse(validTexts.date1)) / 86400000) + 1} дн.`}
        </span>
        <div className="calendar-footer-actions">
          <button type="button" className="text-button" onClick={onCancel}>
            Отмена
          </button>
          <button type="submit" className="primary-button" disabled={!!error}>
            Применить
          </button>
        </div>
      </form>
    </div>
  );
}
