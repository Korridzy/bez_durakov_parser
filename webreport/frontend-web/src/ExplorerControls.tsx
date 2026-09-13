import { useEffect, useRef, useState } from "react";
import {
  Check,
  ListFilter,
  Plus,
  Settings2,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { Select } from "./Select";
import {
  operatorLabels,
  type ExplorerCatalog,
  type ExplorerFilter,
  type ExplorerQuery,
} from "./metrika-types";

type Panel = "metrics" | "dimensions" | "filters" | "settings";
const titles = {
  metrics: "Показатели",
  dimensions: "Группировки",
  filters: "Фильтры",
  settings: "Параметры расчёта",
};

export function ExplorerControls({
  query,
  catalog,
  onChange,
}: {
  query: ExplorerQuery;
  catalog: ExplorerCatalog;
  onChange: (next: ExplorerQuery) => void;
}) {
  const [panel, setPanel] = useState<Panel>();
  const [draft, setDraft] = useState(query);
  const [search, setSearch] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const toggle = (key: Panel) => {
    setDraft(structuredClone(query));
    setSearch("");
    setPanel(panel === key ? undefined : key);
  };
  useEffect(() => {
    if (!panel) return;
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setPanel(undefined);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [panel]);
  const editFilter = (index: number, update: Partial<ExplorerFilter>) =>
    setDraft((current) => ({
      ...current,
      filters: current.filters.map((filter, i) =>
        i === index ? { ...filter, ...update } : filter,
      ),
    }));
  const invalid =
    !draft.metrics.length || draft.filters.some((f) => !f.value.trim());
  const fields = catalog.dimensions.filter((d) =>
    `${d.label} ${d.category}`.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <div
      className="explorer-controls"
      ref={root}
      onKeyDown={(event) => {
        if (event.key === "Escape" && panel) {
          event.stopPropagation();
          setPanel(undefined);
          root.current
            ?.querySelector<HTMLButtonElement>(`[data-panel="${panel}"]`)
            ?.focus();
        }
      }}
    >
      <div className="explorer-control-buttons">
        <button
          data-panel="dimensions"
          aria-expanded={panel === "dimensions"}
          onClick={() => toggle("dimensions")}
        >
          <ListFilter size={15} />
          {query.dimensions.length
            ? query.dimensions
                .map(
                  (key) => catalog.dimensions.find((d) => d.key === key)?.label,
                )
                .join(" · ")
            : "Разбить по…"}
        </button>
        <button
          data-panel="metrics"
          aria-expanded={panel === "metrics"}
          onClick={() => toggle("metrics")}
        >
          <SlidersHorizontal size={15} />
          Показатели <b>{query.metrics.length}</b>
        </button>
        <button
          data-panel="filters"
          aria-expanded={panel === "filters"}
          onClick={() => toggle("filters")}
        >
          <Plus size={15} />
          Фильтры{query.filters.length > 0 && <b>{query.filters.length}</b>}
        </button>
        <button
          data-panel="settings"
          aria-expanded={panel === "settings"}
          aria-label="Параметры расчёта"
          onClick={() => toggle("settings")}
        >
          <Settings2 size={16} />
        </button>
        <label className="explorer-compare">
          <input
            type="checkbox"
            checked={query.compare}
            onChange={(event) =>
              onChange({ ...query, compare: event.target.checked, page: 1 })
            }
          />
          Сравнить с предыдущим периодом
        </label>
      </div>
      {query.filters.length > 0 && (
        <div className="segment-chips" aria-label="Активные фильтры">
          <span>
            {query.filter_mode === "and" ? "Все условия" : "Любое условие"}
          </span>
          {query.filters.map((filter, index) => (
            <button
              key={index}
              title="Убрать условие"
              onClick={() =>
                onChange({
                  ...query,
                  page: 1,
                  filters: query.filters.filter((_, i) => i !== index),
                })
              }
            >
              {catalog.dimensions.find((d) => d.key === filter.field)?.label}{" "}
              {operatorLabels[filter.operator]} <strong>{filter.value}</strong>
              <X size={12} />
            </button>
          ))}
          <button
            className="clear-segment"
            onClick={() => onChange({ ...query, filters: [], page: 1 })}
          >
            Сбросить
          </button>
        </div>
      )}
      {panel && (
        <form
          className={`explorer-panel ${panel}`}
          role="dialog"
          aria-label={titles[panel]}
          onSubmit={(event) => {
            event.preventDefault();
            if (invalid) return;
            const sort =
              draft.metrics.includes(draft.sort) ||
              draft.dimensions.includes(draft.sort)
                ? draft.sort
                : draft.metrics[0];
            onChange({
              ...draft,
              filters: draft.filters.map((f) => ({
                ...f,
                value: f.value.trim(),
              })),
              sort,
              page: 1,
            });
            setPanel(undefined);
          }}
        >
          <header>
            <div>
              <strong>{titles[panel]}</strong>
              <p>
                {panel === "metrics"
                  ? "До 8 показателей. Нажмите карточку, чтобы сменить график."
                  : panel === "dimensions"
                    ? "До 3 группировок: например, страна → устройство → браузер."
                    : panel === "filters"
                      ? "Сегмент применяется к итогам, графику и всем строкам отчёта."
                      : "Параметры одинаковы для графика, таблицы и сравнения."}
              </p>
            </div>
            <button
              className="icon-button"
              type="button"
              aria-label="Закрыть параметры"
              onClick={() => setPanel(undefined)}
            >
              <X size={17} />
            </button>
          </header>
          {panel === "metrics" && (
            <div className="explorer-check-list">
              {catalog.metrics.map((metric) => (
                <label
                  key={metric.key}
                  className={metric.goal && !draft.goal_id ? "unavailable" : ""}
                >
                  <input
                    type="checkbox"
                    checked={draft.metrics.includes(metric.key)}
                    disabled={
                      (metric.goal && !draft.goal_id) ||
                      (!draft.metrics.includes(metric.key) &&
                        draft.metrics.length >= 8)
                    }
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        metrics: event.target.checked
                          ? [...draft.metrics, metric.key]
                          : draft.metrics.filter((k) => k !== metric.key),
                      })
                    }
                  />
                  <span>
                    {metric.label}
                    {metric.goal && !draft.goal_id && (
                      <small>Сначала выберите цель</small>
                    )}
                  </span>
                </label>
              ))}
            </div>
          )}
          {panel === "dimensions" && (
            <>
              <input
                className="explorer-search"
                aria-label="Найти группировку"
                placeholder="Найти группировку…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <div className="chosen-dimensions">
                {draft.dimensions.map((key, i) => (
                  <button
                    type="button"
                    key={key}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        dimensions: draft.dimensions.filter((k) => k !== key),
                      })
                    }
                  >
                    {i + 1}.{" "}
                    {catalog.dimensions.find((d) => d.key === key)?.label}
                    <X size={12} />
                  </button>
                ))}
              </div>
              <div className="explorer-dimensions-list">
                {Array.from(new Set(fields.map((d) => d.category))).map(
                  (category) => (
                    <fieldset key={category}>
                      <legend>{category}</legend>
                      {fields
                        .filter((d) => d.category === category)
                        .map((d) => (
                          <label key={d.key}>
                            <input
                              type="checkbox"
                              checked={draft.dimensions.includes(d.key)}
                              disabled={
                                !draft.dimensions.includes(d.key) &&
                                draft.dimensions.length >= 3
                              }
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  dimensions: event.target.checked
                                    ? [...draft.dimensions, d.key]
                                    : draft.dimensions.filter(
                                        (k) => k !== d.key,
                                      ),
                                })
                              }
                            />
                            {d.label}
                          </label>
                        ))}
                    </fieldset>
                  ),
                )}
              </div>
              <button
                type="button"
                className="text-button"
                onClick={() => setDraft({ ...draft, dimensions: [] })}
              >
                Без группировки · только динамика
              </button>
            </>
          )}
          {panel === "filters" && (
            <>
              <Select
                id="segment-mode"
                label="Правило объединения фильтров"
                value={draft.filter_mode}
                onChange={(value) =>
                  setDraft({ ...draft, filter_mode: value as "and" | "or" })
                }
                options={[
                  { value: "and", label: "Выполнены все условия (И)" },
                  { value: "or", label: "Выполнено любое условие (ИЛИ)" },
                ]}
              />
              <div className="filter-rows">
                {draft.filters.map((filter, index) => (
                  <div className="filter-row" key={index}>
                    <Select
                      id={`filter-field-${index}`}
                      label={`Поле фильтра ${index + 1}`}
                      value={filter.field}
                      options={catalog.dimensions.map((d) => ({
                        value: d.key,
                        label: d.label,
                      }))}
                      onChange={(field) =>
                        editFilter(index, { field, operator: "eq", value: "" })
                      }
                    />
                    <Select
                      id={`filter-operator-${index}`}
                      label={`Условие ${index + 1}`}
                      value={filter.operator}
                      options={(
                        catalog.dimensions.find((d) => d.key === filter.field)
                          ?.operators || ["eq"]
                      ).map((operator) => ({
                        value: operator,
                        label: operatorLabels[operator],
                      }))}
                      onChange={(operator) =>
                        editFilter(index, {
                          operator: operator as ExplorerFilter["operator"],
                        })
                      }
                    />
                    {["new_visitor", "robot", "gender"].includes(
                      filter.field,
                    ) ? (
                      <Select
                        id={`filter-value-${index}`}
                        label={`Значение фильтра ${index + 1}`}
                        value={filter.value}
                        options={[
                          { value: "", label: "Выберите значение" },
                          ...(filter.field === "gender"
                            ? [
                                { value: "male", label: "Мужчины" },
                                { value: "female", label: "Женщины" },
                              ]
                            : [
                                { value: "Yes", label: "Да" },
                                { value: "No", label: "Нет" },
                              ]),
                        ]}
                        onChange={(value) => editFilter(index, { value })}
                      />
                    ) : (
                      <input
                        aria-label={`Значение фильтра ${index + 1}`}
                        placeholder="Значение…"
                        maxLength={150}
                        value={filter.value}
                        onChange={(event) =>
                          editFilter(index, { value: event.target.value })
                        }
                      />
                    )}
                    <button
                      className="icon-button"
                      type="button"
                      aria-label={`Удалить фильтр ${index + 1}`}
                      onClick={() =>
                        setDraft({
                          ...draft,
                          filters: draft.filters.filter((_, i) => i !== index),
                        })
                      }
                    >
                      <X size={15} />
                    </button>
                  </div>
                ))}
              </div>
              <button
                type="button"
                className="text-button"
                disabled={draft.filters.length >= 8}
                onClick={() =>
                  setDraft({
                    ...draft,
                    filters: [
                      ...draft.filters,
                      { field: "country", operator: "eq", value: "" },
                    ],
                  })
                }
              >
                <Plus size={14} />
                Добавить условие
              </button>
              {!draft.filters.length && (
                <p className="explorer-empty-filter">
                  Можно также нажать значение в таблице, чтобы сразу открыть его
                  сегмент.
                </p>
              )}
            </>
          )}
          {panel === "settings" && (
            <div className="explorer-settings-fields">
              <label>
                Точность
                <Select
                  id="report-accuracy"
                  label="Точность расчёта"
                  value={draft.accuracy}
                  options={[
                    {
                      value: "medium",
                      label: "Автоматическая выборка · быстрее",
                    },
                    {
                      value: "full",
                      label: "Все данные · может занять больше времени",
                    },
                  ]}
                  onChange={(value) =>
                    setDraft({
                      ...draft,
                      accuracy: value as ExplorerQuery["accuracy"],
                    })
                  }
                />
              </label>
              <label>
                Атрибуция источников
                <Select
                  id="report-attribution"
                  label="Атрибуция источников"
                  value={draft.attribution}
                  options={[
                    { value: "last_sign", label: "Последний значимый переход" },
                    { value: "last", label: "Последний переход" },
                    { value: "first", label: "Первый переход" },
                  ]}
                  onChange={(value) =>
                    setDraft({
                      ...draft,
                      attribution: value as ExplorerQuery["attribution"],
                    })
                  }
                />
              </label>
              <label className="explorer-check">
                <input
                  type="checkbox"
                  checked={draft.include_undefined}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      include_undefined: event.target.checked,
                    })
                  }
                />
                Показывать неопределённые значения в таблице
              </label>
            </div>
          )}
          <footer>
            <button
              type="button"
              className="text-button"
              onClick={() => setPanel(undefined)}
            >
              Отмена
            </button>
            <button type="submit" className="primary-button" disabled={invalid}>
              <Check size={14} />
              Применить
            </button>
          </footer>
        </form>
      )}
    </div>
  );
}
