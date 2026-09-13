import { useState } from "react";
import { ChevronDown, Search } from "lucide-react";

export type DiscoveredModel = {
  id: string;
  name: string;
  recommendation?: string;
  shutdown_date?: string;
};

export function ModelPicker({
  models,
  value,
  onChange,
  disabled,
}: {
  models: DiscoveredModel[];
  value: string;
  onChange: (id: string) => void;
  disabled: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const recommended = models.filter((model) => model.recommendation);
  const others = models.filter((model) => !model.recommendation);
  const selected = models.find((model) => model.id === value);
  const showCatalog = expanded || !recommended.length;
  const search = query.trim().toLocaleLowerCase();
  const matches = others.filter((model) =>
    `${model.name} ${model.id}`.toLocaleLowerCase().includes(search),
  );

  return (
    <fieldset className="model-picker" disabled={disabled}>
      <legend>Модель</legend>
      {recommended.length > 0 && (
        <div className="model-recommendations">
          {recommended.map((model) => (
            <label className="model-choice model-card" key={model.id}>
              <input
                type="radio"
                name="discovered-model"
                value={model.id}
                checked={value === model.id}
                onChange={() => onChange(model.id)}
              />
              <span>
                <strong>{model.name}</strong>
                <small>{model.recommendation}</small>
              </span>
            </label>
          ))}
        </div>
      )}
      {recommended.length > 0 && others.length > 0 && (
        <button
          type="button"
          className="text-button model-catalog-toggle"
          aria-expanded={expanded}
          aria-controls="model-catalog"
          onClick={() => {
            setExpanded(!expanded);
            setQuery("");
          }}
        >
          {expanded
            ? "Скрыть остальные модели"
            : `Показать остальные модели (${others.length})`}
          <ChevronDown size={15} className={expanded ? "rotated" : ""} />
        </button>
      )}
      {showCatalog && (
        <div id="model-catalog" className="model-catalog">
          <div className="model-search">
            <Search size={16} aria-hidden="true" />
            <input
              type="search"
              aria-label="Поиск модели"
              placeholder="Поиск по названию или ID"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.preventDefault();
              }}
            />
          </div>
          <div className="model-catalog-list" aria-label="Каталог моделей">
            {matches.map((model) => (
              <label className="model-choice model-catalog-row" key={model.id}>
                <input
                  type="radio"
                  name="discovered-model"
                  value={model.id}
                  checked={value === model.id}
                  onChange={() => onChange(model.id)}
                />
                <span>
                  <strong>{model.name}</strong>
                  {model.name !== model.id && <small>{model.id}</small>}
                  {model.shutdown_date && (
                    <small>
                      Отключение:{" "}
                      {model.shutdown_date.split("-").reverse().join(".")}
                    </small>
                  )}
                </span>
              </label>
            ))}
            {!matches.length && (
              <p className="model-catalog-empty" role="status">
                Ничего не найдено. Попробуйте другое название.
              </p>
            )}
          </div>
        </div>
      )}
      {selected && !selected.recommendation && (
        <p className="model-selected" role="status">
          Выбрана: {selected.name}
        </p>
      )}
    </fieldset>
  );
}
