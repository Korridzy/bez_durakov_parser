/**
 * The message input: auto-growing textarea, Enter sends / Shift+Enter breaks
 * the line, one action button that is «Отправить» or, while a run is active,
 * «Остановить». Pure rendering; the decision whether a send is allowed is the
 * caller's (`canSend`).
 */

import { useLayoutEffect, useRef, type FormEvent, type KeyboardEvent } from "react";

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  /** A run is active: the action button stops it. */
  stoppable: boolean;
  canSend: boolean;
  /** A cancel is already on its way: the stop button is disabled. */
  stopping: boolean;
}

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  stoppable,
  canSend,
  stopping,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow: the height follows the content; CSS caps it and scrolls beyond.
  useLayoutEffect(() => {
    const area = textareaRef.current;
    if (area === null) {
      return;
    }
    area.style.height = "auto";
    if (area.scrollHeight > 0) {
      area.style.height = `${String(area.scrollHeight)}px`;
    }
  }, [value]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      onSend();
    }
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSend();
  };

  return (
    <form className="composer" onSubmit={onSubmit}>
      <textarea
        ref={textareaRef}
        className="composer__input"
        aria-label="Сообщение"
        placeholder="Спросите о данных…"
        rows={1}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
      />
      {stoppable ? (
        <button
          type="button"
          className="button button-secondary composer__action"
          onClick={onStop}
          disabled={stopping}
        >
          Остановить
        </button>
      ) : (
        <button type="submit" className="button button-primary composer__action" disabled={!canSend}>
          Отправить
        </button>
      )}
      <p className="composer__hint">Enter - отправить, Shift+Enter - новая строка</p>
    </form>
  );
}
