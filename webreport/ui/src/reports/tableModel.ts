/**
 * Pure helpers that turn a report's `data` into a table and decide which
 * columns can be charted. Values are never rounded or grouped: the preview
 * shows exactly what the tool returned (IS-7).
 */

export type Row = Record<string, unknown>;

export interface TableModel {
  /** Union of the keys of every row, in first-seen order. */
  columns: string[];
  rows: Row[];
}

export function isRow(value: unknown): value is Row {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A non-empty array of row objects becomes a table; anything else does not. */
export function tableModel(data: unknown): TableModel | null {
  if (!Array.isArray(data) || data.length === 0 || !data.every(isRow)) {
    return null;
  }
  const columns: string[] = [];
  const seen = new Set<string>();
  for (const row of data) {
    for (const key of Object.keys(row)) {
      if (!seen.has(key)) {
        seen.add(key);
        columns.push(key);
      }
    }
  }
  return { columns, rows: data };
}

/** Cell text for the table: exact value, `null` as —, booleans as да/нет. */
export function formatCell(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "boolean") {
    return value ? "да" : "нет";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

export function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** A column is numeric when every present value is a finite number and at least one exists. */
export function isNumericColumn(rows: Row[], column: string): boolean {
  let count = 0;
  for (const row of rows) {
    const value = row[column];
    if (value === null || value === undefined) {
      continue;
    }
    if (!isNumber(value)) {
      return false;
    }
    count += 1;
  }
  return count > 0;
}

/** Chartable columns: numeric ones except the first, which labels the axis. */
export function numericColumns(model: TableModel): string[] {
  return model.columns
    .slice(1)
    .filter((column) => isNumericColumn(model.rows, column));
}
