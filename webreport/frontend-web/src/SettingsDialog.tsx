import { useState } from "react";
import { Check, Eye, EyeOff, KeyRound, Plus, Trash2 } from "lucide-react";
import type { Workspace } from "./types";
import { api, post } from "./api";
import { Alert, Modal, Spinner } from "./ui";
import { accentPresets, defaultAccent } from "./theme";

export function SettingsDialog({
  workspace,
  onClose,
  onRefresh,
  initialAdd = false,
  onSelect,
  accent,
  onAccent,
}: {
  accent: string;
  onAccent: (color: string) => void;
  workspace: Workspace;
  onClose: () => void;
  onRefresh: () => Promise<Workspace>;
  initialAdd?: boolean;
  onSelect: (id: string) => void;
}) {
  const [adding, setAdding] = useState(initialAdd),
    [provider, setProvider] = useState("openai"),
    [token, setToken] = useState(""),
    [base, setBase] = useState(""),
    [name, setName] = useState(""),
    [modelId, setModelId] = useState(""),
    [remember, setRemember] = useState(false),
    [visible, setVisible] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [models, setModels] = useState<{ id: string; name: string }[]>([]);
  const [removeId, setRemoveId] = useState("");
  const discover = async () => {
    setBusy(true);
    setError("");
    try {
      const data = await post<{ models: typeof models }>(
        "/model-connections/discover",
        { provider, token, base_url: base },
      );
      setModels(data.models);
      setModelId(data.models[0]?.id || "");
      if (!data.models.length)
        setError("Нет доступных текстовых моделей с подходящим API.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!modelId) {
      await discover();
      return;
    }
    setBusy(true);
    setError("");
    try {
      const model = await post<{ id: string }>("/model-connections", {
        provider,
        token,
        base_url: base,
        model_id: modelId,
        name,
        remember,
      });
      setToken("");
      await onRefresh();
      onSelect(model.id);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={adding ? "Добавить свою модель" : "Настройки"}
      onClose={onClose}
    >
      {adding ? (
        <form className="connection-form" onSubmit={save}>
          <div className="field">
            <label htmlFor="model-provider">Поставщик</label>
            <select
              id="model-provider"
              value={provider}
              disabled={busy}
              onChange={(e) => {
                setProvider(e.target.value);
                setModels([]);
                setModelId("");
                setToken("");
                setError("");
              }}
            >
              {workspace.model_providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          {provider === "custom" && (
            <div className="field">
              <label htmlFor="base-url">Base URL</label>
              <input
                id="base-url"
                type="url"
                placeholder="https://api.example.com/v1"
                required
                value={base}
                onChange={(e) => {
                  setBase(e.target.value);
                  setModelId("");
                  setModels([]);
                }}
              />
              <small className="field-help">
                Совместимый с OpenAI Chat Completions API с вызовом
                инструментов.
              </small>
            </div>
          )}
          <div className="field">
            <label htmlFor="model-key">API-ключ</label>
            <div className="secret-input">
              <input
                id="model-key"
                autoComplete="off"
                type={visible ? "text" : "password"}
                value={token}
                onChange={(e) => {
                  setToken(e.target.value);
                  setModels([]);
                  setModelId("");
                }}
                spellCheck={false}
                required
                disabled={busy}
                placeholder="Вставьте ключ"
              />
              <button
                type="button"
                className="icon-button"
                aria-label={visible ? "Скрыть ключ" : "Показать ключ"}
                onClick={() => setVisible(!visible)}
              >
                {visible ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
          {models.length > 0 && (
            <>
              <div className="field">
                <label htmlFor="custom-model">Модель</label>
                <select
                  id="custom-model"
                  value={modelId}
                  onChange={(e) => setModelId(e.target.value)}
                  disabled={busy}
                >
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="model-label">
                  Название <span>необязательно</span>
                </label>
                <input
                  id="model-label"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={modelId}
                  maxLength={100}
                />
              </div>
            </>
          )}
          <label className="check-field">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
            <span>
              Запомнить ключ на этом компьютере
              <small>
                {remember
                  ? "Хранится на сервере в зашифрованном виде."
                  : "Ключ действует до перезапуска сервера."}
              </small>
            </span>
          </label>
          {error && <Alert>{error}</Alert>}
          <div className="form-bottom">
            <button
              type="button"
              className="text-button"
              onClick={() => setAdding(false)}
            >
              Все модели
            </button>
            <button className="primary-button" disabled={busy || !token.trim()}>
              {busy ? (
                <Spinner label="Проверяю…" />
              ) : models.length ? (
                <>
                  <Check size={16} />
                  Добавить модель
                </>
              ) : (
                "Получить список моделей"
              )}
            </button>
          </div>
        </form>
      ) : (
        <div className="settings-body">
          <div className="settings-profile">
            <span className="avatar large-avatar">Л</span>
            <div>
              <h3>Локальный профиль</h3>
              <p>Проекты и история сохраняются на этом компьютере.</p>
            </div>
          </div>
          <section
            className="appearance-settings"
            aria-labelledby="appearance-title"
          >
            <div className="settings-section-title">
              <h3 id="appearance-title">Акцентный цвет</h3>
              <button
                className="text-button"
                onClick={() => onAccent(defaultAccent)}
              >
                Сбросить
              </button>
            </div>
            <p>Немного цвета в важных деталях.</p>
            <div className="accent-options">
              {accentPresets.map((preset) => (
                <button
                  key={preset.color}
                  className="accent-swatch"
                  style={{ background: preset.color }}
                  aria-label={preset.name}
                  aria-pressed={accent === preset.color}
                  title={preset.name}
                  onClick={() => onAccent(preset.color)}
                >
                  {accent === preset.color && <Check size={18} />}
                </button>
              ))}
              <label className="custom-accent" title="Выбрать свой цвет">
                <input
                  type="color"
                  value={accent}
                  onChange={(e) => onAccent(e.target.value)}
                  aria-label="Свой акцентный цвет"
                />
                <span>Свой цвет</span>
              </label>
            </div>
            <div className="accent-preview">
              <span>Покажи, что изменилось</span>
              <small>Цвет сохраняется в этом браузере</small>
            </div>
          </section>
          <div className="settings-section-title">
            <h3>Модели</h3>
            <span>Для всех проектов</span>
          </div>
          {workspace.models.map((model) => (
            <div className="connection-row" key={model.id}>
              <span className="model-icon">
                <KeyRound size={18} />
              </span>
              <div className="connection-info">
                <strong>{model.name}</strong>
                <span>
                  {model.system ? "Системная модель" : model.provider}
                  {model.connected ? "" : " · Нужно подключить ключ заново"}
                </span>
              </div>
              {!model.system &&
                (removeId === model.id ? (
                  <>
                    <button
                      className="danger-button"
                      onClick={async () => {
                        try {
                          await api("/model-connections/" + model.id, {
                            method: "DELETE",
                          });
                          await onRefresh();
                          setRemoveId("");
                        } catch (e) {
                          setError((e as Error).message);
                        }
                      }}
                    >
                      Удалить
                    </button>
                    <button
                      className="text-button"
                      onClick={() => setRemoveId("")}
                    >
                      Отмена
                    </button>
                  </>
                ) : (
                  <button
                    className="icon-button"
                    aria-label={"Удалить " + model.name}
                    onClick={() => setRemoveId(model.id)}
                  >
                    <Trash2 size={16} />
                  </button>
                ))}
            </div>
          ))}
          {error && <Alert>{error}</Alert>}
          <button className="add-connection" onClick={() => setAdding(true)}>
            <Plus size={18} />
            Добавить свою модель
          </button>
        </div>
      )}
    </Modal>
  );
}
