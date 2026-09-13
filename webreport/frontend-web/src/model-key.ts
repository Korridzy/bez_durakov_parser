// Match workspace.models.normalize_model_key. Providers own key validity;
// do not assume a fixed prefix or length for opaque credentials.
export function modelKeyError(raw: string): string {
  const key = raw.trim();
  if (!key) return "Введите API-ключ.";
  if (/^(?:authorization\s*:|bearer\s)/i.test(key))
    return "Вставьте только ключ, без Authorization и Bearer.";
  if (/\s/.test(key))
    return "В ключе есть пробелы или переносы строк. Скопируйте его заново.";
  if (/[^\x21-\x7e]/.test(key))
    return "В ключе есть посторонние или невидимые символы. Скопируйте его заново.";
  return "";
}
