import { useEffect, useState } from "react";
import {
  ArrowUp,
  ChevronDown,
  Database,
  Maximize2,
  Minimize2,
  Plus,
  Square,
} from "lucide-react";
import type { Model, Source } from "./types";
import { Menu, MenuItem, ProviderIcon } from "./ui";

export const efforts: Record<string, string> = {
  auto: "Авто",
  low: "Низкое",
  medium: "Среднее",
  high: "Высокое",
};
type Props = {
  sources: Source[];
  hasDataset: boolean;
  onSource: (source: Source) => void;
  onManageSources: () => void;
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onCancel: () => void;
  running: boolean;
  disabled: boolean;
  models: Model[];
  modelId: string;
  onModel: (id: string) => void;
  effort: string;
  onEffort: (v: string) => void;
  onAddModel: () => void;
  onAddSource: () => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
};
export function Composer(p: Props) {
  const [expanded, setExpanded] = useState(false),
    [menu, setMenu] = useState("");
  const model = p.models.find((m) => m.id === p.modelId) || p.models[0];
  const connectedCount =
    p.sources.filter((s) => s.connected).length + Number(p.hasDataset);
  const sourceNoun = new Intl.PluralRules("ru").select(connectedCount);
  const sourceStatus =
    connectedCount === 0
      ? "Нет подключённых источников"
      : `${connectedCount} ${sourceNoun === "one" ? "источник подключён" : sourceNoun === "few" ? "источника подключено" : "источников подключено"}`;
  useEffect(() => {
    const el = p.inputRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height =
        Math.min(el.scrollHeight, expanded ? window.innerHeight * 0.52 : 240) +
        "px";
    }
  }, [p.value, expanded, p.inputRef]);
  return (
    <div className={"composer " + (expanded ? "expanded" : "")}>
      <div className="composer-sources" aria-label="Источники проекта">
        {p.hasDataset && (
          <span className="attached-source dataset-source">
            <Database size={16} />
            <span>Данные проекта</span>
            <span className="source-status-dot" />
          </span>
        )}
        {p.sources.map((source) => (
          <button
            key={source.id}
            className={
              "attached-source " + (!source.connected ? "disconnected" : "")
            }
            onClick={() =>
              source.connected ? p.onSource(source) : p.onManageSources()
            }
            title={
              source.connected
                ? "Открыть " + source.name
                : source.name + " · Подключите заново"
            }
          >
            <ProviderIcon id={source.provider} />
            <span>{source.name}</span>
            <span className="source-status-dot" />
          </button>
        ))}
        <button
          className={"source-status " + (!connectedCount ? "empty" : "")}
          onClick={p.onManageSources}
        >
          {!p.sources.length && !p.hasDataset && <Database size={15} />}
          {sourceStatus}
        </button>
      </div>
      <button
        className="expand-input icon-button"
        aria-label={expanded ? "Уменьшить поле ввода" : "Развернуть поле ввода"}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
      </button>
      <textarea
        ref={p.inputRef}
        value={p.value}
        onChange={(e) => p.onChange(e.target.value)}
        placeholder="Спросите о ваших данных"
        rows={1}
        aria-label="Сообщение"
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            if (!p.running && !p.disabled && p.value.trim()) p.onSend();
          }
        }}
      />
      <div className="composer-toolbar">
        <button
          className="icon-button add-context"
          aria-label="Добавить источник данных"
          onClick={p.onAddSource}
        >
          <Plus size={21} />
        </button>
        <div className="composer-choices">
          <Menu
            className="model-menu"
            label={
              <>
                <span>{model?.name || "Выберите модель"}</span>
                <ChevronDown size={14} />
              </>
            }
            ariaLabel="Выбрать модель"
            open={menu === "model"}
            onToggle={() => setMenu(menu === "model" ? "" : "model")}
            onClose={() => setMenu("")}
          >
            <div className="menu-label">Модель</div>
            {p.models.map((m) => (
              <MenuItem
                key={m.id}
                selected={m.id === p.modelId}
                onClick={() => {
                  p.onModel(m.id);
                  setMenu("");
                }}
                disabled={!m.connected}
              >
                <span className="model-option">
                  <strong>{m.name}</strong>
                  <small>
                    {m.system ? "Системная" : m.provider}
                    {!m.connected ? " · Подключите ключ" : ""}
                    {m.system && m.available === false ? " · Недоступна" : ""}
                  </small>
                </span>
              </MenuItem>
            ))}
            <MenuItem
              onClick={() => {
                setMenu("");
                p.onAddModel();
              }}
            >
              <Plus size={16} />
              Добавить свою модель
            </MenuItem>
          </Menu>
          {(model?.efforts.length || 0) > 1 && (
            <Menu
              className="effort-menu"
              label={
                <>
                  <span>{efforts[p.effort] || "Авто"}</span>
                  <ChevronDown size={13} />
                </>
              }
              ariaLabel="Усилие рассуждений"
              open={menu === "effort"}
              onToggle={() => setMenu(menu === "effort" ? "" : "effort")}
              onClose={() => setMenu("")}
            >
              <div className="menu-label">Усилие рассуждений</div>
              {model?.efforts.map((e) => (
                <MenuItem
                  key={e}
                  selected={p.effort === e}
                  onClick={() => {
                    p.onEffort(e);
                    setMenu("");
                  }}
                >
                  {efforts[e]}
                </MenuItem>
              ))}
            </Menu>
          )}
        </div>
        {p.running ? (
          <button
            className="send stop"
            aria-label="Остановить ответ"
            onClick={p.onCancel}
          >
            <Square size={14} fill="currentColor" />
          </button>
        ) : (
          <button
            className="send"
            aria-label="Отправить сообщение"
            disabled={!p.value.trim() || p.disabled}
            onClick={p.onSend}
          >
            <ArrowUp size={21} />
          </button>
        )}
      </div>
    </div>
  );
}
